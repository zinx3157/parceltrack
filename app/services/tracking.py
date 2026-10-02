"""Tracking synchronisation engine: poll carriers, store events, raise alerts."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..carriers import get_adapter
from ..config import settings
from ..models import Parcel, ParcelEvent, SyncRun, utcnow

log = logging.getLogger("parceldesk.sync")

FINISHED_STATUSES = {"delivered", "cancelled", "returned"}


def _event_hash(parcel_id: int, occurred_at: datetime, status_text: str, location: str) -> str:
    basis = f"{parcel_id}|{occurred_at.isoformat()}|{status_text.strip().lower()}|{location.strip().lower()}"
    return hashlib.sha1(basis.encode()).hexdigest()


def add_event(db: Session, parcel: Parcel, *, occurred_at: datetime, status: str, status_text: str = "",
              location: str = "", description: str = "", source: str = "api", raw: dict | None = None) -> ParcelEvent | None:
    """Insert an event unless it is already known. Returns the new event or None."""
    h = _event_hash(parcel.id, occurred_at, status_text or description, location)
    exists = db.query(ParcelEvent.id).filter(
        ParcelEvent.parcel_id == parcel.id, ParcelEvent.event_hash == h
    ).first()
    if exists:
        return None
    event = ParcelEvent(
        parcel_id=parcel.id, occurred_at=occurred_at, status=status,
        status_text=status_text or description[:300], location=location, description=description,
        source=source, event_hash=h, raw_json=json.dumps(raw or {})[:20000],
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:  # concurrent insert of the same event
        db.rollback()
        return None
    return event


def refresh_parcel_from_events(db: Session, parcel: Parcel) -> tuple[str, bool]:
    """Recompute parcel state from its stored events. Returns (old_status, changed)."""
    old_status = parcel.status
    events = (db.query(ParcelEvent)
              .filter(ParcelEvent.parcel_id == parcel.id)
              .order_by(ParcelEvent.occurred_at.desc()).all())
    if events:
        latest = events[0]
        parcel.status = latest.status
        parcel.status_text = latest.status_text or parcel.status_text
        parcel.last_event_at = latest.occurred_at
        if latest.status == "delivered":
            parcel.delivered_at = parcel.delivered_at or latest.occurred_at
        elif latest.status != "delivered":
            parcel.delivered_at = None
    return old_status, old_status != parcel.status


def sync_parcel(db: Session, parcel: Parcel, *, force: bool = False, notify: bool = True) -> dict:
    """Poll one parcel's carrier and store anything new."""
    result = {"parcel_id": parcel.id, "tracking_number": parcel.tracking_number,
              "carrier": parcel.carrier, "added": 0, "error": "", "status_changed": False,
              "old_status": parcel.status, "new_status": parcel.status}

    if parcel.carrier == "manual":
        result["error"] = "manual tracking"
        return result
    if not parcel.sync_enabled:
        result["error"] = "sync disabled for this parcel"
        return result
    if parcel.status in FINISHED_STATUSES and not force:
        result["error"] = "finished"
        return result

    adapter = get_adapter(parcel.carrier, settings)
    if not adapter.configured:
        msg = f"{parcel.carrier.upper()} credentials not configured — using manual updates"
        parcel.last_sync_error = msg
        parcel.last_synced_at = utcnow()
        result["error"] = msg
        return result

    try:
        res = adapter.track(parcel.tracking_number, parcel)
    except Exception as exc:  # never let one carrier break the sync loop
        log.exception("Carrier adapter crashed for %s", parcel.tracking_number)
        res = None
        parcel.last_sync_error = f"{type(exc).__name__}: {exc}"
        result["error"] = parcel.last_sync_error

    if res is not None and not res.ok:
        parcel.last_sync_error = res.error
        parcel.last_synced_at = utcnow()
        result["error"] = res.error
        return result

    if res is not None:
        added = 0
        for ev in res.events:
            if add_event(db, parcel, occurred_at=ev.occurred_at, status=ev.status,
                         status_text=ev.status_text, location=ev.location,
                         description=ev.description, source="api", raw=ev.raw):
                added += 1
        if res.eta and (not parcel.eta or res.eta < parcel.eta):
            parcel.eta = res.eta
        parcel.last_sync_error = ""
        parcel.last_synced_at = utcnow()

        old_status, changed = refresh_parcel_from_events(db, parcel)
        result.update(added=added, status_changed=changed, old_status=old_status, new_status=parcel.status)

        if changed and notify:
            from . import alerts
            alerts.on_status_change(db, parcel, old_status, parcel.status)

    db.commit()
    return result


def sync_all(db: Session, *, trigger: str = "scheduler", limit: int | None = None,
             notify: bool = True, force: bool = False,
             statuses: list[str] | None = None) -> SyncRun:
    """Poll every eligible parcel.

    `statuses` restricts the run to specific statuses — the scheduler uses it for the
    hourly "out for delivery" sweep, which is where parcels move fastest.
    """
    run = SyncRun(trigger=trigger)
    db.add(run)
    db.commit()

    stmt = db.query(Parcel).filter(Parcel.carrier != "manual", Parcel.sync_enabled.is_(True))
    if statuses:
        stmt = stmt.filter(Parcel.status.in_(statuses))
    elif not force:
        stmt = stmt.filter(~Parcel.status.in_(FINISHED_STATUSES))
    parcels = stmt.order_by(Parcel.last_synced_at.asc().nullsfirst()).limit(limit or 500).all()

    errors, events_added, updated = 0, 0, 0
    messages: list[str] = []
    for parcel in parcels:
        try:
            res = sync_parcel(db, parcel, force=force, notify=notify)
        except Exception as exc:  # pragma: no cover
            log.exception("sync_parcel failed for %s", parcel.id)
            db.rollback()
            errors += 1
            messages.append(f"{parcel.tracking_number}: {exc}")
            continue
        events_added += res["added"]
        if res["status_changed"]:
            updated += 1
        if res["error"] and res["error"] not in ("finished", "manual tracking", "sync disabled for this parcel"):
            errors += 1
            messages.append(f"{parcel.tracking_number}: {res['error']}")

    run.parcels_checked = len(parcels)
    run.events_added = events_added
    run.parcels_updated = updated
    run.errors = errors
    run.finished_at = utcnow()
    run.message = "; ".join(messages[:10])
    db.commit()
    log.info("Sync %s: checked=%s new_events=%s updated=%s errors=%s",
             trigger, len(parcels), events_added, updated, errors)
    return run


def stuck_parcels(db: Session) -> list[dict]:
    """Parcels that look stuck — customs holds and silent shipments."""
    now = utcnow()
    out = []
    for parcel in db.query(Parcel).filter(Parcel.status.in_(["customs", "in_transit", "exception"])).all():
        reference = parcel.last_event_at or parcel.created_at
        age = (now - reference).days if reference else 0
        if parcel.status == "customs" and age >= settings.stuck_customs_days:
            out.append({"parcel": parcel, "kind": "stuck_customs", "days": age})
        elif parcel.status in ("in_transit", "exception") and age >= settings.stuck_transit_days:
            out.append({"parcel": parcel, "kind": "stuck_transit", "days": age})
    return out
