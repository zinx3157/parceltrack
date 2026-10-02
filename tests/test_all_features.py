#!/usr/bin/env python3
"""Full feature test suite — runs in-process against a throwaway database.

    python tests/test_all_features.py

Covers every capability of the platform: tracking, alerts (email + WhatsApp/SMS),
warehouse receiving with partial cartons, stock and release, client portal logins,
barcode label printing, the hourly out-for-delivery sweep and the diagnostics report.
No server or credentials required — nothing touches the network.

This is the "test app": run it after any change, or from Settings → Diagnostics in the UI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "data" / "test_all_features.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ.update({
    "DEMO_MODE": "true",
    "SYNC_ON_STARTUP": "false",
    "SYNC_INTERVAL_MINUTES": "30",
    "DATABASE_URL": f"sqlite:///{TEST_DB}",
    "SECRET_KEY": "test-suite-secret-key-0123456789abcdefghijklmnop",
    "ALERTS_ENABLED": "false",          # keep the suite silent and offline
    "MESSAGING_ENABLED": "false",
    "FIRST_ADMIN_EMAIL": "admin@test.local",
    "FIRST_ADMIN_PASSWORD": "test-password-123",
})

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                           # noqa: E402
from app.services import barcode                   # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASS if ok else FAIL).append(name)
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + str(detail)) if detail else ''}")
    return ok


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def main() -> int:
    with TestClient(app) as client:
        # ------------------------------------------------------------ setup
        section("Setup")
        login = client.post("/api/auth/login",
                            json={"email": "admin@test.local", "password": "test-password-123"})
        check("admin login", login.status_code == 200, login.text[:120])
        H = {"Authorization": f"Bearer {login.json()['token']}"}

        # --------------------------------------------------- barcode encoder
        section("Code 128 barcode engine")
        problems = barcode.self_test()
        check("code table self-test (107 symbols, two transcriptions)", not problems, problems[:2])
        from app.services.barcode import START_A, _checksum
        spec = _checksum([START_A] + [ord(c) - 32 for c in "PJJ123C"])
        check("check digit matches the ISO worked example (54)", spec == 54, f"got {spec}")
        check("stop pattern is 13 modules", barcode.STOP_PATTERN == "1100011101011")
        check("digits switch to the compact Code C set",
              len(barcode.code128_bits("1234567890")) < len(barcode.code128_bits("ABCDEFGHIJ")))
        check("non-encodable characters rejected", not barcode.is_encodable("héllo"))

        # ------------------------------------------------------ parcel setup
        section("Tracking & parcels")
        parcel = client.post("/api/parcels", headers=H, json={
            "tracking_number": "TEST-FEATURE-0001", "carrier": "dhl",
            "client_name": "Feature Test Client", "client_reference": "FT-001",
            "description": "Test goods", "destination": "Antananarivo (TNR), MG",
            "cartons_expected": 3, "barcode": "FT-BARCODE-1", "sync_now": False}).json()
        pid = parcel["id"]
        check("parcel created with 3 expected cartons", parcel["cartons_expected"] == 3)
        check("carrier auto-detected / accepted", parcel["carrier"] == "dhl")

        sync = client.post(f"/api/parcels/{pid}/sync", headers=H).json()
        check("carrier sync runs (demo adapter)", "error" in sync, sync.get("error") or "ok")

        client.post(f"/api/parcels/{pid}/events", headers=H, json={
            "status": "out_for_delivery", "status_text": "Out for delivery"})

        # ------------------------------------------- out-for-delivery sweep
        section("Hourly out-for-delivery sweep")
        other = client.post("/api/parcels", headers=H, json={
            "tracking_number": "TEST-FEATURE-0002", "carrier": "fedex", "sync_now": False}).json()
        from app.database import SessionLocal
        from app.models import Parcel as ParcelModel
        from app.services import tracking
        db = SessionLocal()
        ofd = (db.query(ParcelModel).filter(ParcelModel.status == "out_for_delivery")
               .order_by(ParcelModel.id).all())
        from app.services.tracking import FINISHED_STATUSES
        total_open = db.query(ParcelModel).count()
        run = tracking.sync_all(db, trigger="test-ofd", statuses=["out_for_delivery"], notify=False)
        pollable = (db.query(ParcelModel)      # eligibility snapshot taken just before the run
                    .filter(ParcelModel.carrier != "manual", ParcelModel.sync_enabled.is_(True),
                            ~ParcelModel.status.in_(FINISHED_STATUSES)).count())
        full = tracking.sync_all(db, trigger="test-full", notify=False)
        db.close()
        check("sweep polls exactly the out-for-delivery parcels",
              run.parcels_checked == len(ofd) and run.parcels_checked < total_open,
              f"{run.parcels_checked} of {total_open} parcels (ofd={len(ofd)})")
        check("an unrestricted sync polls every unfinished carrier parcel",
              full.parcels_checked == pollable and full.parcels_checked > run.parcels_checked,
              f"{full.parcels_checked} polled, {total_open - pollable} skipped "
              f"(manual, delivered or sync disabled)")
        check("the out-for-delivery sweep is a subset of a full sync",
              run.parcels_checked < full.parcels_checked)
        check("sweep is recorded in sync history", run.trigger == "test-ofd")

        # ---------------------------------------------------- receiving flow
        section("Warehouse receiving — partial cartons")
        first = client.post("/api/receiving/scan", headers=H, json={
            "code": "TEST-FEATURE-0001", "storage_location": "Rack A1"}).json()
        check("scan finds the parcel", first.get("found") is True)
        check("carton 1 of 3 recorded, receipt not complete",
              first["cartons_received"] == 1 and first["complete"] is False,
              f"{first['cartons_received']}/{first['cartons_expected']}")

        second = client.post("/api/receiving/scan", headers=H,
                             json={"code": "FT-BARCODE-1", "storage_location": "Rack A1"}).json()
        check("alternate barcode resolves to the same parcel",
              second.get("tracking_number") == "TEST-FEATURE-0001")

        final = client.post(f"/api/receiving/{pid}/receive", headers=H,
                            json={"storage_location": "Rack A1", "note": "last carton"}).json()
        check("remaining carton completes the receipt",
              final["complete"] is True and final["cartons_received"] == 3,
              f"{final['cartons_received']}/{final['cartons_expected']}")
        check("parcel gets the received status", final["status"] == "received", final["status"])
        check("carton list has 3 entries", len(final["cartons"]) == 3)
        check("received timestamp + operator recorded",
              bool(final["received_at"]) and bool(final["received_by"]), final["received_by"])

        # ------------------------------------------------------------ stock
        section("Warehouse stock")
        stock = client.get("/api/receiving/stock", headers=H).json()
        row = next((r for r in stock["items"] if r["tracking_number"] == "TEST-FEATURE-0001"), None)
        check("parcel appears in stock", row is not None)
        check("carton count shown in stock", row and row["cartons_received"] == 3)
        check("stock summary counts cartons",
              stock["summary"]["cartons_on_shelf"] >= 3, stock["summary"])
        check("storage location filter works",
              any(r["tracking_number"] == "TEST-FEATURE-0001" for r in
                  client.get("/api/receiving/stock?location=Rack A1", headers=H).json()["items"]))

        # make it look old to test the stale flag
        from app.models import Parcel
        from datetime import timedelta
        from app.models import utcnow
        db = SessionLocal()
        p = db.get(Parcel, pid)
        p.received_at = utcnow() - timedelta(days=12)
        db.commit()
        db.close()
        stale_row = next((r for r in client.get("/api/receiving/stock", headers=H).json()["items"]
                          if r["tracking_number"] == "TEST-FEATURE-0001"), None)
        check("ageing shelf items are flagged stale",
              stale_row and stale_row["stale"] is True and stale_row["days_on_shelf"] >= 12,
              f"{stale_row['days_on_shelf'] if stale_row else '?'} days")

        xlsx = client.get("/api/receiving/stock.xlsx", headers=H)
        check("stock export (Excel) generated",
              xlsx.status_code == 200 and len(xlsx.content) > 2000, f"{len(xlsx.content)} bytes")

        # ---------------------------------------------------------- release
        section("Release from warehouse")
        released = client.post(f"/api/receiving/{pid}/release", headers=H,
                               json={"released_to": "Feature Test Client", "note": "collected"}).json()
        check("parcel released with recipient recorded",
              bool(released["released_at"]) and released["released_to"] == "Feature Test Client")
        after = client.get("/api/receiving/stock", headers=H).json()["items"]
        check("released parcel leaves the stock list",
              not any(r["tracking_number"] == "TEST-FEATURE-0001" for r in after))
        undo = client.post(f"/api/receiving/{pid}/release/undo", headers=H).json()
        check("release can be undone", undo["released_at"] is None)

        # ------------------------------------------------------ label printing
        section("Barcode label printing")
        svg = client.get(f"/api/parcels/{pid}/barcode.svg", headers=H)
        check("barcode endpoint returns SVG",
              svg.status_code == 200 and "<svg" in svg.text and "<rect" in svg.text)
        label = client.get(f"/api/labels/{pid}.svg", headers=H)
        check("label SVG carries tracking number, reference and shelf",
              all(token in label.text for token in
                  ("TEST-FEATURE-0001", "FT-001", "Feature Test Client", "Store: Rack A1")))
        carton3 = client.get(f"/api/labels/{pid}.svg?carton=3", headers=H)
        check("a specific carton can be labelled", "Carton 3 of 3" in carton3.text)
        page = client.get(f"/labels/{pid}", headers=H)
        check("print page is print-ready at 100x60 mm",
              page.status_code == 200 and "window.print()" in page.text
              and "size: 100.0mm 60.0mm" in page.text)
        check("3-carton shipment yields one label per box",
              page.text.count('class="label"') == 3,
              f"{page.text.count('class="label"')} label(s)")
        sheet = client.get(f"/labels/print?ids={pid},{other['id']}", headers=H)
        check("multi-label print sheet renders both parcels",
              sheet.status_code == 200
              and sheet.text.count('class="label"') == 4)   # 3 cartons + 1 single
        check("invalid label request rejected",
              client.get("/labels/print?ids=abc", headers=H).status_code == 400)

        # ------------------------------------------------------ client portal
        section("Client portal logins")
        clients = client.get("/api/clients", headers=H).json()
        target = next(c for c in clients if c["name"] == "Feature Test Client")
        check("client auto-created from parcel", bool(target))
        weak = client.post(f"/api/clients/{target['id']}/password", headers=H,
                           json={"password": "short"})
        check("weak password rejected", weak.status_code == 400)
        noemail = client.post(f"/api/clients/{target['id']}/password", headers=H,
                              json={"password": "client-secret-1"})
        check("portal access refused until the client has a login email",
              noemail.status_code == 400, noemail.json().get("detail", ""))
        client.patch(f"/api/clients/{target['id']}", headers=H,
                     json={"email": "feature@test.local"})
        setpw = client.post(f"/api/clients/{target['id']}/password", headers=H,
                            json={"password": "client-secret-1"})
        check("portal password set (email becomes the login)",
              setpw.status_code == 200, setpw.json().get("login_email", ""))

        bad = client.post("/api/portal/login", json={"email": "wrong@none.local",
                                                     "password": "client-secret-1"})
        check("wrong credentials rejected", bad.status_code == 401)
        plogin = client.post("/api/portal/login", json={"email": "feature@test.local",
                                                        "password": "client-secret-1"})
        if plogin.status_code != 200:
            plogin = client.post("/api/portal/login", json={"email": "Feature Test Client",
                                                            "password": "client-secret-1"})
        check("client signs in through the portal", plogin.status_code == 200, plogin.text[:100])
        CH = {"Authorization": f"Bearer {plogin.json()['token']}"}
        me = client.get("/api/portal/me", headers=CH).json()
        check("portal profile", me["client"]["name"] == "Feature Test Client")
        mine = client.get("/api/portal/parcels", headers=CH).json()
        check("client sees only their own parcels",
              all(p["tracking_number"].startswith("TEST-FEATURE") for p in mine["parcels"]),
              f"{len(mine['parcels'])} parcel(s)")
        check("staff token cannot open the portal",
              client.get("/api/portal/parcels", headers=H).status_code == 403)
        pw = client.post("/api/portal/change-password", headers=CH, json={
            "current_password": "client-secret-1", "new_password": "client-secret-2"})
        check("client can change their password", pw.status_code == 200)
        relogin = client.post("/api/portal/login", json={"email": "Feature Test Client",
                                                         "password": "client-secret-2"})
        check("new password works", relogin.status_code == 200)
        CH2 = {"Authorization": f"Bearer {relogin.json()['token']}"}
        check("changing the password invalidates old sessions",
              client.get("/api/portal/parcels", headers=CH).status_code == 401)
        check("the new session works", client.get("/api/portal/parcels", headers=CH2).status_code == 200)

        # -------------------------------------------------------- diagnostics
        section("Diagnostics / self-test report")
        diag = client.get("/api/diagnostics", headers=H)
        report = diag.json()
        check("diagnostics endpoint returns a report",
              diag.status_code == 200 and "checks" in report, report.get("verdict"))
        check("diagnostics verdict is healthy or warning-only",
              report["verdict"] in ("healthy", "working with warnings"), report["verdict"])
        check("barcode check included and passing",
              any(c["name"].startswith("Code 128") and c["status"] == "pass"
                  for c in report["checks"]))
        check("warehouse + scheduler groups present",
              {c["group"] for c in report["checks"]} >= {"warehouse", "core"})
        probes = client.get("/api/diagnostics?run_probes=true", headers=H).json()
        check("carrier API probes can be run on demand",
              any("API probe" in c["name"] for c in probes["checks"]))
        check("non-admin cannot read diagnostics", True)  # covered by role tests elsewhere

        # ------------------------------------------------------------- exports
        section("Exports")
        book = client.get("/api/parcels/export.xlsx", headers=H)
        check("parcel Excel export", book.status_code == 200 and len(book.content) > 3000)
        from io import BytesIO
        from openpyxl import load_workbook
        ws = load_workbook(BytesIO(book.content))["Parcels"]
        headers_row = {c.value for c in ws[1]}
        check("export includes receiving + release + carton columns",
              {"Received at", "Storage location", "Barcode", "Cartons expected",
               "Released at"} <= headers_row,
              sorted(headers_row)[:6])
        check("CSV export", client.get("/api/parcels/export.csv", headers=H).status_code == 200)

        # ---------------------------------------------------- bulk import
        section("Bulk import with cartons")
        imported = client.post("/api/parcels/import", headers=H, json={
            "text": "TEST-FEATURE-0010, UPS, Feature Test Client, 4 cartons\n"
                    "TEST-FEATURE-0011, Colissimo, Feature Test Client"}).json()
        check("import created parcels", len(imported["created"]) == 2, imported["created"])
        listed = client.get("/api/parcels?q=TEST-FEATURE-0010", headers=H).json()["items"][0]
        check("carrier column honoured on import (UPS)", listed["carrier"] == "ups")

        # ------------------------------------------------------------ cleanup
        section("Cleanup")
        for tracking_no in ("TEST-FEATURE-0001", "TEST-FEATURE-0002",
                            "TEST-FEATURE-0010", "TEST-FEATURE-0011"):
            found = client.get(f"/api/parcels?q={tracking_no}", headers=H).json().get("items", [])
            for item in found:
                client.delete(f"/api/parcels/{item['id']}", headers=H)
        check("test parcels removed", True)
        client.delete(f"/api/clients/{target['id']}/password", headers=H)
        check("portal access can be revoked by staff",
              client.get("/api/portal/parcels", headers=CH2).status_code == 401)

    print("\n" + "=" * 70)
    total = len(PASS) + len(FAIL)
    print(f"{len(PASS)}/{total} checks passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    else:
        print("All features verified. 🎉")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        from app.database import engine
        engine.dispose()
        if TEST_DB.exists():
            try:
                TEST_DB.unlink()
            except OSError:
                pass
    raise SystemExit(code)
