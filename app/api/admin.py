"""Admin endpoints: carrier health, sync control, notifications, runtime settings."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..carriers import carrier_status
from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Client, Notification, Parcel, ParcelEvent, Setting, SyncRun, User, utcnow
from ..schemas import SettingsUpdate, TestEmailRequest, TestMessageRequest
from ..security import current_user, require_admin
from ..services import alerts, messaging, runtime, tracking
from ..services.tracking import stuck_parcels
from ..services.parcels import parcel_to_dict

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/carriers")
def carriers(_: User = Depends(current_user)):
    return {
        "demo_mode": settings.demo_mode,
        "carriers": carrier_status(settings),
    }


@router.get("/sync/runs")
def sync_runs(limit: int = 20, _: User = Depends(current_user), db: Session = Depends(get_db)):
    runs = db.query(SyncRun).order_by(SyncRun.id.desc()).limit(limit).all()
    return [
        {"id": r.id, "started_at": r.started_at.isoformat() if r.started_at else None,
         "finished_at": r.finished_at.isoformat() if r.finished_at else None,
         "trigger": r.trigger, "parcels_checked": r.parcels_checked,
         "events_added": r.events_added, "parcels_updated": r.parcels_updated,
         "errors": r.errors, "message": r.message}
        for r in runs
    ]


@router.post("/sync/run")
def run_sync(background: BackgroundTasks, limit: int = 200, notify: bool = True,
             _: User = Depends(current_user)):
    def _run():
        db = SessionLocal()
        try:
            tracking.sync_all(db, trigger="manual", limit=limit, notify=notify)
        finally:
            db.close()

    background.add_task(_run)
    return {"ok": True, "message": "Sync started — check Sync history for the result"}


@router.get("/stuck")
def stuck(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [
        {**parcel_to_dict(item["parcel"]), "kind": item["kind"], "stuck_days": item["days"]}
        for item in stuck_parcels(db)
    ]


@router.get("/notifications")
def notifications(limit: int = 50, _: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).order_by(Notification.id.desc()).limit(limit).all()
    return [
        {"id": n.id, "parcel_id": n.parcel_id, "kind": n.kind, "subject": n.subject,
         "channel": n.channel, "recipients": n.recipients, "ok": n.ok, "error": n.error,
         "created_at": n.created_at.isoformat() if n.created_at else None}
        for n in rows
    ]


@router.post("/notifications/test")
def test_email(payload: TestEmailRequest, user: User = Depends(require_admin)):
    to = payload.to or user.email
    ok, error = alerts.send_email(
        f"[{settings.company_name}] ParcelDesk test alert",
        "This is a test email from your ParcelDesk installation.\n"
        "If you received it, SMTP alerts are configured correctly.",
        [to],
    )
    if not ok:
        raise HTTPException(400, error)
    return {"ok": True, "to": to}


@router.get("/messaging")
def messaging_status(_: User = Depends(current_user), db: Session = Depends(get_db)):
    status = messaging.provider_status()
    status["recipients"] = messaging.recipients_for(db, None)
    return status


@router.post("/messaging/test")
def test_message(payload: TestMessageRequest, user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    target = payload.to or user.phone or (settings.messaging_number_list or [""])[0]
    if not target:
        raise HTTPException(400, "No phone number supplied — add one to your user profile "
                                 "or set MESSAGING_RECIPIENTS in .env")
    results = messaging.send_text(payload.text, [target])
    result = results[0] if results else {"ok": False, "error": "no provider"}
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "send failed")
    return {"ok": True, "to": result["to"], "channel": result["channel"]}


@router.post("/notifications/digest")
def send_digest_now(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    count = alerts.daily_digest(db)
    return {"ok": True, "open_parcels": count}


@router.post("/notifications/stuck")
def run_stuck_check(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"ok": True, "alerts_created": alerts.notify_stuck(db)}


@router.get("/diagnostics")
def diagnostics(run_probes: bool = False, user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    """Self-test of the whole installation — the "is everything working?" report.

    Set run_probes=true to also make a live call to every configured carrier API
    (uses a real tracking number already in your database).
    """
    import datetime as _dt
    import os
    import shutil
    import time

    from ..services import barcode, messaging, receiving
    from ..scheduler import _scheduler as sched   # the scheduler this process started

    checks: list[dict] = []

    def add(name: str, status: str, detail: str = "", group: str = "core") -> None:
        checks.append({"name": name, "status": status, "detail": detail, "group": group})

    # ---------------------------------------------------------------- database
    try:
        start = time.perf_counter()
        parcels = db.query(Parcel).count()
        events = db.query(ParcelEvent).count()
        clients = db.query(Client).count()
        users = db.query(User).count()
        ms = (time.perf_counter() - start) * 1000
        add("Database read", "pass",
            f"{parcels} parcels · {events} events · {clients} clients · {users} users "
            f"({ms:.0f} ms)", "core")
    except Exception as exc:
        add("Database read", "fail", str(exc)[:200], "core")

    try:
        db.merge(Setting(key="diag_probe", value=_dt.datetime.utcnow().isoformat()))
        db.commit()
        db.query(Setting).filter(Setting.key == "diag_probe").delete()
        db.commit()
        add("Database write", "pass", "write + delete round-trip OK", "core")
    except Exception as exc:
        db.rollback()
        add("Database write", "fail", str(exc)[:200], "core")

    try:
        from ..database import engine
        from ..migrations import sync_schema
        pending = sync_schema(engine)
        add("Schema up to date", "warn" if pending else "pass",
            f"added missing column(s): {', '.join(pending)}" if pending
            else "every model column exists in the database", "core")
    except Exception as exc:
        add("Schema up to date", "fail", str(exc)[:200], "core")

    # ---------------------------------------------------------------- storage
    try:
        if settings.database_url.startswith("sqlite"):
            data_dir = os.path.dirname(settings.database_url.replace("sqlite:///", "")) or "."
            probe = os.path.join(data_dir, ".diag_probe")
            with open(probe, "w") as fh:
                fh.write("ok")
            os.remove(probe)
            free_gb = shutil.disk_usage(data_dir).free / (1024 ** 3)
            add("File storage writable", "pass" if free_gb > 0.2 else "warn",
                f"{os.path.abspath(data_dir)} — {free_gb:.1f} GB free", "core")
        else:
            add("File storage writable", "pass", "external database (no local SQLite file)",
                "core")
    except Exception as exc:
        add("File storage writable", "fail", str(exc)[:200], "core")

    # -------------------------------------------------------------- scheduler
    try:
        if sched and sched.running:
            jobs = ", ".join(f"{j.id} → {str(j.next_run_time)[:19]}" for j in sched.get_jobs())
            add("Background scheduler", "pass", jobs[:260], "core")
            ids = [j.id for j in sched.get_jobs()]
            add("Hourly out-for-delivery sweep",
                "pass" if ("ofd_sync" in ids or not settings.ofd_sync_enabled) else "warn",
                f"every {settings.ofd_sync_minutes} min" if settings.ofd_sync_enabled
                else "disabled", "core")
        else:
            add("Background scheduler", "warn",
                "not running — automatic syncing only happens inside the web app process",
                "core")
    except Exception as exc:
        add("Background scheduler", "fail", str(exc)[:200], "core")

    # ----------------------------------------------------------- barcode engine
    problems = barcode.self_test()
    if problems:
        add("Code 128 label engine", "fail", "; ".join(problems[:3]), "labels")
    else:
        modules = len(barcode.code128_bits("1234567890"))
        add("Code 128 label engine", "pass",
            f"107 symbols verified against two transcriptions · {modules} modules for "
            f"a 10-digit number", "labels")

    # ---------------------------------------------------------------- carriers
    from ..carriers import carrier_status, get_adapter
    status = carrier_status(settings)
    live = [c["name"] for c in status if c["configured"] and c["name"] != "manual"]
    waiting = [c["name"] for c in status if not c["configured"] and c["name"] != "manual"]
    add("Carrier credentials", "pass" if live else "warn",
        f"connected: {', '.join(live) or 'none'} · awaiting credentials: "
        f"{', '.join(waiting) or 'none'}", "carriers")
    add("Carrier mode", "warn" if settings.demo_mode else "pass",
        "DEMO — carrier responses are simulated" if settings.demo_mode
        else "live carrier APIs", "carriers")

    if run_probes:
        for name in live:
            adapter = get_adapter(name, settings)
            sample = db.query(Parcel).filter(Parcel.carrier == name).first()
            if not sample:
                add(f"{name.upper()} API probe", "warn",
                    "no parcel of this carrier to test with", "carriers")
                continue
            try:
                result = adapter.track(sample.tracking_number, sample)
                add(f"{name.upper()} API probe", "pass" if result.ok else "warn",
                    f"{len(result.events)} event(s) for {sample.tracking_number}" if result.ok
                    else result.error[:180], "carriers")
            except Exception as exc:
                add(f"{name.upper()} API probe", "fail", str(exc)[:180], "carriers")

    # ------------------------------------------------------------------ alerts
    if settings.smtp_host:
        add("Email alerts (SMTP)", "pass",
            f"{settings.smtp_host}:{settings.smtp_port}, from {settings.smtp_from}", "alerts")
    else:
        add("Email alerts (SMTP)", "warn",
            "SMTP_HOST not set — alerts are logged in the app but not emailed", "alerts")

    msg = messaging.provider_status()
    add("WhatsApp / SMS alerts", "pass" if msg["configured"] else "warn",
        msg["provider_label"] + (f" — {msg['hint']}" if msg.get("hint") else ""), "alerts")
    numbers = messaging.recipients_for(db, None)
    add("Message recipients", "pass" if numbers else "warn",
        f"{len(numbers)} number(s): {', '.join(numbers[:4])}" if numbers
        else "no phone numbers on users/clients and no MESSAGING_RECIPIENTS", "alerts")

    total_alerts = db.query(Notification).count()
    failed_alerts = db.query(Notification).filter(Notification.ok.is_(False)).count()
    add("Alert log", "pass" if not failed_alerts else "warn",
        f"{total_alerts} recorded, {failed_alerts} not delivered", "alerts")

    # -------------------------------------------------------------- warehouse
    summary = receiving.stock_summary(db)
    add("Warehouse stock", "pass",
        f"{summary['in_warehouse']} parcel(s) / {summary['cartons_on_shelf']} carton(s) on "
        f"the shelf · {summary['stale']} past {summary['stale_after_days']} days", "warehouse")

    # -------------------------------------------------------------- tracking
    stuck = tracking.stuck_parcels(db)
    add("SLA watch", "pass" if not stuck else "warn",
        f"{len(stuck)} parcel(s) past SLA" if stuck else "nothing past SLA", "core")
    finished = db.query(Parcel).filter(Parcel.status.in_(list(tracking.FINISHED_STATUSES))).count()
    add("Quota efficiency", "pass",
        f"{finished} finished parcel(s) excluded from polling", "carriers")

    counts = {"pass": 0, "warn": 0, "fail": 0}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    return {
        "generated_at": utcnow().isoformat(),
        "run_probes": run_probes,
        "summary": counts,
        "verdict": ("healthy" if counts["fail"] == 0 and counts["warn"] == 0
                    else "working with warnings" if counts["fail"] == 0
                    else "needs attention"),
        "checks": checks,
        "app": {"name": settings.app_name, "version": "1.1.0",
                "demo_mode": settings.demo_mode, "company": settings.company_name},
    }


@router.get("/settings")
def get_settings_endpoint(_: User = Depends(current_user), db: Session = Depends(get_db)):
    values = runtime.current_values()
    values.update({
        "demo_mode": settings.demo_mode,
        "smtp_configured": bool(settings.smtp_host),
        "smtp_host": settings.smtp_host,
        "smtp_from": settings.smtp_from,
        "alert_on_statuses": settings.alert_on_statuses,
    })
    return values


@router.put("/settings")
def update_settings(payload: SettingsUpdate, user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "No changes supplied")
    for key, value in changes.items():
        runtime.set_setting(db, key, value)
    # reschedule the background job if the interval changed
    if "sync_interval_minutes" in changes:
        from ..scheduler import reschedule_sync
        try:
            reschedule_sync(int(changes["sync_interval_minutes"]))
        except Exception:
            pass
    if "ofd_sync_minutes" in changes or "ofd_sync_enabled" in changes:
        from ..scheduler import reschedule_ofd
        try:
            reschedule_ofd(int(runtime.current_values()["ofd_sync_minutes"]),
                           bool(runtime.current_values()["ofd_sync_enabled"]))
        except Exception:
            pass
    return runtime.current_values()
