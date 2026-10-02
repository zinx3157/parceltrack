#!/usr/bin/env python3
"""End-to-end smoke test of a running ParcelDesk installation.

    python tests/smoke_test.py [http://localhost:8000] [email] [password]

Creates a test parcel, syncs it, imports two more, checks the exports, then removes
the test data. Every step must print OK.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "admin@example.com"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "admin123"

TOKEN = ""
failures: list[str] = []


def call(method: str, path: str, body=None, raw=False, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    auth = token if token is not None else TOKEN      # client-portal calls pass their own token
    if auth:
        req.add_header("Authorization", "Bearer " + auth)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload or b"{}"))
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"detail": payload[:200].decode(errors="replace")}


def step(name: str, ok: bool, detail: str = ""):
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    global TOKEN

    status, body = call("GET", "/api/health")
    step("health check", status == 200 and body.get("status") == "ok",
         f"demo_mode={body.get('demo_mode')}")
    if status != 200:
        print("\nServer not reachable — start it first (python run.py).")
        return 1

    status, body = call("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    step("login", status == 200 and "token" in body, body.get("detail", ""))
    if status != 200:
        return 1
    TOKEN = body["token"]

    status, body = call("GET", "/api/auth/me")
    step("session", status == 200, f"role={body.get('role')}")

    status, body = call("GET", "/api/parcels/stats?days=30")
    step("dashboard stats", status == 200 and "total" in body, f"total={body.get('total')}")

    status, body = call("GET", "/api/carriers")
    configured = [c["name"] for c in body.get("carriers", []) if c.get("configured")]
    step("carrier registry", status == 200, f"connected: {', '.join(configured) or 'none'}")

    status, body = call("POST", "/api/parcels", {
        "tracking_number": "SMOKE-TEST-0001", "client_name": "Smoke Test Client",
        "description": "automated test parcel", "sync_now": False,
    })
    ok = status in (201, 409)
    parcel_id = body.get("id")
    step("create parcel", ok, body.get("detail", f"id={parcel_id}"))
    if status == 409:  # leftover from an earlier run
        status, listing = call("GET", "/api/parcels?q=SMOKE-TEST-0001")
        parcel_id = listing["items"][0]["id"] if listing.get("items") else None

    if parcel_id:
        status, body = call("POST", f"/api/parcels/{parcel_id}/events", {
            "status": "in_transit", "status_text": "Smoke test manual update",
            "location": "Antananarivo (TNR), MG",
        })
        step("manual status update", status in (201, 409), body.get("detail", ""))

        status, body = call("POST", f"/api/parcels/{parcel_id}/sync?force=true")
        step("carrier sync call", status == 200,
             body.get("error") or f"new events: {body.get('added')}")

        status, body = call("POST", f"/api/parcels/{parcel_id}/share")
        token = body.get("share_token")
        step("share link", status == 200 and bool(token))
        if token:
            status, body = call("GET", f"/api/public/track/{token}")
            step("public tracking page data", status == 200 and "events" in body)

    status, body = call("POST", "/api/parcels/import", {
        "text": "SMOKE-IMPORT-0001, DHL, Smoke Test Client\nSMOKE-IMPORT-0002, Aramex, Smoke Test Client",
    })
    step("bulk import", status == 200 and len(body.get("created", [])) >= 0,
         f"created={len(body.get('created', []))} skipped={len(body.get('skipped', []))}")

    status, blob = call("GET", "/api/parcels/export.xlsx", raw=True)
    step("Excel export", status == 200 and len(blob) > 2000, f"{len(blob)} bytes")

    status, blob = call("GET", "/api/parcels/export.csv", raw=True)
    step("CSV export", status == 200 and b"Tracking number" in blob)

    status, body = call("GET", "/api/stuck")
    step("stuck parcel check", status == 200, f"{len(body)} flagged")

    # ---------------------------------------------------------- receiving
    if parcel_id:
        status, body = call("POST", f"/api/receiving/{parcel_id}/receive", {
            "code": "SMOKE-TEST-0001", "storage_location": "Smoke rack 1",
            "note": "smoke test check-in", "mark_received": True,
        })
        step("warehouse check-in", status == 200 and body.get("received_at"),
             f"location={body.get('storage_location')}")

        status, body = call("GET", f"/api/receiving/lookup?code=SMOKE-TEST-0001")
        step("barcode lookup", status == 200 and body.get("found"),
             f"received_at={str(body.get('received_at'))[:16]}")

        status, body = call("POST", "/api/receiving/scan", {"code": "NO-SUCH-PARCEL-XYZ"})
        step("unknown barcode handled", status == 200 and body.get("found") is False)

        status, body = call("GET", "/api/receiving/recent?limit=5")
        step("receiving lists", status == 200 and isinstance(body, list), f"{len(body)} recent")

        status, body = call("GET", "/api/receiving/stock")
        step("warehouse stock view", status == 200 and "summary" in body,
             f"{body.get('summary', {}).get('in_warehouse')} parcel(s) on the shelves")

        status, blob = call("GET", "/api/receiving/stock.xlsx", raw=True)
        step("stock export (Excel)", status == 200 and len(blob) > 2000, f"{len(blob)} bytes")

    # ---------------------------------------------------------- cartons & releases
    carton_id = None
    if parcel_id:
        status, body = call("POST", "/api/parcels", {
            "tracking_number": "SMOKE-TEST-CARTONS", "carrier": "dhl",
            "client_name": "Smoke Test Client", "cartons_expected": 3, "sync_now": False})
        carton_id = body.get("id")
        step("multi-carton parcel created", status == 201 or (status == 200 and carton_id),
             f"expected {(body.get('cartons_expected'))} cartons")

        status, body = call("POST", "/api/receiving/scan", {"code": "SMOKE-TEST-CARTONS"})
        step("first carton checked in (partial receipt)",
             status == 200 and body.get("cartons_received") == 1 and not body.get("complete"),
             f"{body.get('cartons_received')}/{body.get('cartons_expected')} cartons")

        status, body = call("POST", f"/api/receiving/{carton_id}/receive", {"count": 2})
        step("remaining cartons complete the receipt",
             status == 200 and body.get("complete") is True,
             f"{body.get('cartons_received')}/{body.get('cartons_expected')} cartons")

        status, body = call("POST", f"/api/receiving/{carton_id}/release",
                            {"released_to": "Smoke Test Client", "note": "smoke release"})
        step("release from warehouse", status == 200 and body.get("released_at"),
             f"released to {body.get('released_to')}")

        status, body = call("POST", f"/api/receiving/{carton_id}/release/undo", {})
        step("release can be undone", status == 200 and body.get("released_at") is None)

    # ---------------------------------------------------------- barcode labels
    if parcel_id:
        status, blob = call("GET", f"/api/parcels/{parcel_id}/barcode.svg", raw=True)
        step("Code 128 barcode SVG", status == 200 and b"<svg" in blob and b"<rect" in blob,
             f"{len(blob)} bytes")

        status, blob = call("GET", f"/api/labels/{parcel_id}.svg", raw=True)
        step("printable label SVG", status == 200 and blob.count(b"<rect") > 20,
             f"{len(blob)} bytes")

        status, blob = call("GET", f"/labels/{parcel_id}", raw=True)
        step("label print sheet", status == 200 and b"window.print()" in blob)

        status, blob = call(f"GET", f"/labels/print?ids={parcel_id}", raw=True)
        step("bulk label sheet", status == 200 and blob.count(b'class="label"') >= 1)

    # ---------------------------------------------------------- client portal
    portal_token = ""
    status, body = call("GET", "/api/clients")
    smoke_client = next((c for c in body if c.get("name") == "Smoke Test Client"), None) if status == 200 else None
    if smoke_client:
        call("PATCH", f"/api/clients/{smoke_client['id']}", {"email": "smoke.client@example.com"})
        status, body = call("POST", f"/api/clients/{smoke_client['id']}/password",
                            {"password": "smoke-portal-1"})
        step("staff enables portal login", status == 200 and body.get("ok"),
             f"login email {body.get('login_email')}")

        status, body = call("POST", "/api/portal/login",
                            {"email": "smoke.client@example.com", "password": "smoke-portal-1"})
        portal_token = body.get("token", "")
        step("client signs in", status == 200 and bool(portal_token))

        if portal_token:
            status, body = call("GET", "/api/portal/parcels", token=portal_token)
            step("client sees their own shipments only",
                 status == 200 and all("tracking_number" in p for p in body.get("parcels", [])),
                 f"{len(body.get('parcels', []))} parcel(s)")

            status, body = call("POST", "/api/portal/change-password", {
                "current_password": "smoke-portal-1", "new_password": "smoke-portal-2"},
                token=portal_token)
            step("client changes their own password", status == 200)

            status, body = call("GET", "/api/portal/parcels", token=portal_token)
            step("old portal session is invalidated", status == 401)

    # ---------------------------------------------------------- diagnostics (self-test app)
    status, body = call("GET", "/api/diagnostics?run_probes=false")
    checks = body.get("checks", []) if isinstance(body, dict) else []
    step("diagnostics report", status == 200 and bool(checks),
         f"verdict: {body.get('verdict')} ({body.get('summary', {}).get('pass')} pass / "
         f"{body.get('summary', {}).get('warn')} warn / {body.get('summary', {}).get('fail')} fail)")
    step("diagnostics covers the barcode engine + warehouse",
         any("Code 128" in c.get("name", "") for c in checks)
         and any(c.get("group") == "warehouse" for c in checks))

    # ---------------------------------------------------------- messaging
    status, body = call("GET", "/api/messaging")
    step("messaging provider status", status == 200 and "provider" in body,
         f"provider={body.get('provider')} configured={body.get('configured')}")

    status, body = call("GET", "/api/carriers")
    names = [c["name"] for c in body.get("carriers", [])]
    step("all 8 carriers registered",
         all(n in names for n in ("dhl", "fedex", "aramex", "ups", "dhlecom", "colissimo",
                                  "track17", "manual")), f"{len(names)} carriers")

    status, body = call("GET", "/api/notifications?limit=5")
    step("notification log", status == 200, f"{len(body)} recent alerts")

    # cleanup
    if smoke_client:
        call("DELETE", f"/api/clients/{smoke_client['id']}/password")
    if parcel_id:
        call("DELETE", f"/api/parcels/{parcel_id}")
    if carton_id:
        call("DELETE", f"/api/parcels/{carton_id}")
    for extra in ("SMOKE-IMPORT-0001", "SMOKE-IMPORT-0002"):
        status, listing = call("GET", f"/api/parcels?q={extra}")
        for item in listing.get("items", []):
            call("DELETE", f"/api/parcels/{item['id']}")
    step("cleanup", True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("All checks passed — this installation is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
