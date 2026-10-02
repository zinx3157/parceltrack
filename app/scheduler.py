"""Background scheduler: periodic carrier sync, stuck-parcel checks, daily digest."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .database import SessionLocal

log = logging.getLogger("parceldesk.scheduler")
_scheduler: BackgroundScheduler | None = None


def _with_session(func):
    def wrapper():
        db = SessionLocal()
        try:
            func(db)
        except Exception:
            log.exception("Scheduled job %s failed", func.__name__)
            db.rollback()
        finally:
            db.close()

    wrapper.__name__ = func.__name__
    return wrapper


def _sync_job(db):
    from .services import tracking
    tracking.sync_all(db, trigger="scheduler")


def _ofd_job(db):
    # parcels on the delivery van move fastest — poll them hourly so "delivered"
    # is picked up quickly instead of waiting for the next full cycle
    from .services import tracking
    if not settings.ofd_sync_enabled:
        return
    tracking.sync_all(db, trigger="ofd", statuses=["out_for_delivery"], limit=200)


def _stuck_job(db):
    from .services import alerts
    count = alerts.notify_stuck(db)
    if count:
        log.info("Stuck-parcel alerts created: %s", count)


def _digest_job(db):
    from .services import alerts
    if settings.alerts_enabled:
        alerts.daily_digest(db)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})
    _scheduler.add_job(_with_session(_sync_job), "interval",
                       minutes=max(5, settings.sync_interval_minutes),
                       id="carrier_sync", next_run_time=None)
    if settings.ofd_sync_enabled:
        _scheduler.add_job(_with_session(_ofd_job), "interval",
                           minutes=max(10, settings.ofd_sync_minutes), id="ofd_sync")
    _scheduler.add_job(_with_session(_stuck_job), "cron", hour=8, minute=0, id="stuck_check")
    _scheduler.add_job(_with_session(_digest_job), "cron",
                       hour=settings.daily_digest_hour, minute=5, id="daily_digest")
    _scheduler.start()
    log.info("Scheduler started (sync every %s min)", settings.sync_interval_minutes)
    return _scheduler


def reschedule_sync(minutes: int) -> None:
    if _scheduler and _scheduler.running:
        _scheduler.reschedule_job("carrier_sync", trigger="interval", minutes=max(5, minutes))
        settings.sync_interval_minutes = minutes
        log.info("Sync interval changed to %s minutes", minutes)


def reschedule_ofd(minutes: int, enabled: bool | None = None) -> None:
    """Apply changes to the hourly out-for-delivery sweep without a restart."""
    settings.ofd_sync_minutes = max(10, int(minutes))
    if enabled is not None:
        settings.ofd_sync_enabled = bool(enabled)
    if _scheduler and _scheduler.running:
        try:
            _scheduler.remove_job("ofd_sync")
        except Exception:
            pass
        if settings.ofd_sync_enabled:
            _scheduler.add_job(_with_session(_ofd_job), "interval",
                               minutes=max(10, settings.ofd_sync_minutes), id="ofd_sync")
        log.info("Out-for-delivery sweep: %s every %s min",
                 "on" if settings.ofd_sync_enabled else "off", settings.ofd_sync_minutes)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
    _scheduler = None
