"""Warehouse receiving: barcode lookup, carton check-in, stock and release."""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import Parcel, ReceiptLine, User, utcnow
from .parcels import parcel_to_dict
from .tracking import add_event, refresh_parcel_from_events

RECEIVED_STATUS = "received"


def normalize_code(code: str) -> str:
    """Barcodes vary in separators/case — compare on a normalised form."""
    return re.sub(r"[\s\-_]", "", (code or "")).upper()


# ------------------------------------------------------------------ lookup
def lookup(db: Session, code: str) -> dict:
    """Find a parcel by tracking number or alternate barcode."""
    if not normalize_code(code):
        return {"found": False, "reason": "empty"}

    exact = (db.query(Parcel)
             .options(joinedload(Parcel.client), joinedload(Parcel.receipts))
             .filter(or_(Parcel.tracking_number == code, Parcel.barcode == code,
                         Parcel.tracking_number.ilike(code), Parcel.barcode.ilike(code)))
             .first())
    if not exact:
        exact = (db.query(Parcel)
                 .options(joinedload(Parcel.client), joinedload(Parcel.receipts))
                 .filter(or_(Parcel.tracking_number.ilike(f"%{code}%"),
                             Parcel.barcode.ilike(f"%{code}%")))
                 .first())
    if not exact:
        return {"found": False, "reason": "not_found", "code": code,
                "suggestion": "Add it as a new parcel"}

    return parcel_receiving_state(db, exact)


def parcel_receiving_state(db: Session, parcel: Parcel) -> dict:
    """Lookup payload: parcel fields plus carton/receipt progress."""
    count = db.query(func.count(ReceiptLine.id)).filter(
        ReceiptLine.parcel_id == parcel.id).scalar() or 0
    expected = max(1, parcel.cartons_expected or 1)
    data = parcel_to_dict(parcel)
    data.update({
        "found": True,
        "cartons_expected": expected,
        "cartons_received": count,
        "cartons_outstanding": max(0, expected - count),
        "complete": count >= expected,
        "received_at": parcel.received_at.isoformat() if parcel.received_at else None,
        "received_by": parcel.received_by,
        "released_at": parcel.released_at.isoformat() if parcel.released_at else None,
        "released_to": parcel.released_to,
        "cartons": [
            {"carton_no": r.carton_no, "received_at": r.received_at.isoformat(),
             "received_by": r.received_by, "storage_location": r.storage_location,
             "note": r.note}
            for r in sorted(parcel.receipts, key=lambda r: r.carton_no)
        ],
    })
    return data


# ------------------------------------------------------------- check-in
def receive_carton(db: Session, parcel: Parcel, *, user: User | None = None,
                   storage_location: str = "", note: str = "", count: int = 1,
                   mark_received: bool = True) -> dict:
    """Record one (or more) cartons arriving. Completes the receipt when the
    expected carton count is reached."""
    who = (user.name or user.email) if user else "system"
    expected = max(1, parcel.cartons_expected or 1)
    existing = db.query(func.count(ReceiptLine.id)).filter(
        ReceiptLine.parcel_id == parcel.id).scalar() or 0

    added = 0
    for _ in range(max(1, min(count, 50))):
        existing += 1
        db.add(ReceiptLine(parcel_id=parcel.id, carton_no=existing, received_at=utcnow(),
                           received_by=who, storage_location=storage_location[:120],
                           note=note[:400]))
        added += 1

    parcel.received_by = who
    if storage_location:
        parcel.storage_location = storage_location.strip()[:120]

    complete = existing >= expected
    if complete:
        parcel.received_at = parcel.received_at or utcnow()
    detail = " — ".join(x for x in [storage_location.strip(), note.strip()] if x)
    text = (f"Carton {existing} of {expected} received at warehouse"
            f"{(' (' + detail + ')') if detail else ''}")
    if complete:
        text = f"Received at warehouse — {expected} of {expected} cartons" + \
               (f" ({detail})" if detail else "")
    add_event(db, parcel, occurred_at=utcnow(),
              status=RECEIVED_STATUS if (complete and mark_received) else parcel.status,
              status_text=text, location=parcel.destination or "",
              description=note or "", source="manual")
    if complete and mark_received:
        refresh_parcel_from_events(db, parcel)
    db.commit()
    state = parcel_receiving_state(db, parcel)
    state.update({"cartons_added": added, "message":
                  (f"Receipt complete — {expected} of {expected} cartons in"
                   if complete else f"Carton {existing} of {expected} checked in")})
    return state


def receive(db: Session, parcel: Parcel, *, user: User | None = None,
            storage_location: str = "", note: str = "", mark_received: bool = True) -> Parcel:
    """Check in a whole parcel (all remaining cartons)."""
    expected = max(1, parcel.cartons_expected or 1)
    have = db.query(func.count(ReceiptLine.id)).filter(
        ReceiptLine.parcel_id == parcel.id).scalar() or 0
    if have >= expected and parcel.received_at and not storage_location and not note:
        return parcel    # nothing new to record
    receive_carton(db, parcel, user=user, storage_location=storage_location, note=note,
                   count=max(0, expected - have) or 1, mark_received=mark_received)
    return parcel


def undo_receive(db: Session, parcel: Parcel) -> Parcel:
    """Clear the receiving record (marked in error)."""
    db.query(ReceiptLine).filter(ReceiptLine.parcel_id == parcel.id).delete()
    parcel.received_at = None
    parcel.received_by = ""
    parcel.storage_location = ""
    add_event(db, parcel, occurred_at=utcnow(), status=parcel.status,
              status_text="Warehouse receipt cleared", source="manual")
    db.commit()
    return parcel


# --------------------------------------------------------------- release
def release(db: Session, parcel: Parcel, *, released_to: str = "", note: str = "",
            user: User | None = None) -> Parcel:
    """Hand the goods over to the consignee (leaves the warehouse)."""
    who = (user.name or user.email) if user else "system"
    parcel.released_at = utcnow()
    parcel.released_to = (released_to or (parcel.client.name if parcel.client else "")).strip()[:200]
    parcel.released_by = who
    add_event(db, parcel, occurred_at=utcnow(), status=parcel.status,
              status_text=f"Released from warehouse to {parcel.released_to or 'consignee'}"
                          + (f" — {note}" if note else ""),
              source="manual")
    db.commit()
    return parcel


def undo_release(db: Session, parcel: Parcel) -> Parcel:
    parcel.released_at = None
    parcel.released_to = ""
    parcel.released_by = ""
    add_event(db, parcel, occurred_at=utcnow(), status=parcel.status,
              status_text="Warehouse release cancelled", source="manual")
    db.commit()
    return parcel


# ----------------------------------------------------------------- stock
def stock_rows(db: Session, *, query: str = "", location: str = "",
               include_released: bool = False, limit: int = 2000) -> list[dict]:
    """Everything currently sitting in the warehouse (received, not released)."""
    counts = dict(db.query(ReceiptLine.parcel_id, func.count(ReceiptLine.id))
                  .group_by(ReceiptLine.parcel_id).all())
    stmt = db.query(Parcel).options(joinedload(Parcel.client))
    if not include_released:
        stmt = stmt.filter(Parcel.released_at.is_(None))
    if location:
        stmt = stmt.filter(Parcel.storage_location.ilike(f"%{location}%"))
    if query:
        like = f"%{query}%"
        stmt = stmt.filter(or_(Parcel.tracking_number.ilike(like), Parcel.barcode.ilike(like),
                               Parcel.description.ilike(like), Parcel.client_reference.ilike(like)))
    parcels = stmt.all()
    now = utcnow()
    rows = []
    for parcel in parcels:
        received = counts.get(parcel.id, 0)
        if not received:
            continue                      # never checked in
        on_shelf = (now - (parcel.received_at or parcel.created_at)).days if parcel.received_at else 0
        rows.append({
            **parcel_to_dict(parcel),
            "cartons_received": received,
            "cartons_expected": max(1, parcel.cartons_expected or 1),
            "complete": received >= max(1, parcel.cartons_expected or 1),
            "days_on_shelf": on_shelf,
            "stale": (parcel.released_at is None
                      and on_shelf >= settings.warehouse_stale_days),
            "released_at": parcel.released_at.isoformat() if parcel.released_at else None,
            "released_to": parcel.released_to,
        })
    rows.sort(key=lambda r: (r["released_at"] is not None, -(r["days_on_shelf"] or 0)))
    return rows[:limit]


def stock_summary(db: Session) -> dict:
    rows = stock_rows(db)
    released = stock_rows(db, include_released=True)
    released_count = sum(1 for r in released if r["released_at"])
    return {
        "in_warehouse": len(rows),
        "stale": sum(1 for r in rows if r["stale"]),
        "cartons_on_shelf": sum(r["cartons_received"] for r in rows),
        "released_total": released_count,
        "locations": sorted({r["storage_location"] for r in rows if r["storage_location"]}),
        "stale_after_days": settings.warehouse_stale_days,
    }


# --------------------------------------------------------------- lists
def recently_received(db: Session, limit: int = 20) -> list[dict]:
    rows = (db.query(Parcel).options(joinedload(Parcel.client))
            .filter(Parcel.received_at.is_not(None))
            .order_by(Parcel.received_at.desc()).limit(limit).all())
    counts: dict[int, int] = {}
    if rows:
        counts = dict(db.query(ReceiptLine.parcel_id, func.count(ReceiptLine.id))
                      .filter(ReceiptLine.parcel_id.in_([p.id for p in rows]))
                      .group_by(ReceiptLine.parcel_id).all())
    out = []
    for parcel in rows:
        expected = max(1, parcel.cartons_expected or 1)
        received = counts.get(parcel.id, 0)
        out.append({
            **parcel_to_dict(parcel),
            "cartons_received": received,
            "cartons_expected": expected,
            "complete": received >= expected,
            "released_at": parcel.released_at.isoformat() if parcel.released_at else None,
            "released_to": parcel.released_to,
        })
    return out


def pending_inbound(db: Session, limit: int = 20) -> list[dict]:
    """On their way but not yet (fully) checked in."""
    rows = (db.query(Parcel).options(joinedload(Parcel.client))
            .filter(Parcel.received_at.is_(None),
                    Parcel.status.in_(["registered", "picked_up", "in_transit", "customs",
                                       "out_for_delivery"]))
            .order_by(Parcel.created_at.asc()).limit(limit).all())
    return [parcel_to_dict(p) for p in rows]
