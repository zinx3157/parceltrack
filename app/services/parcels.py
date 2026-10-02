"""Parcel queries, serialisation and shared helpers."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..models import Parcel, ParcelEvent, utcnow

OPEN_STATUSES = ["registered", "picked_up", "received", "in_transit", "customs",
                 "out_for_delivery", "exception", "unknown"]


def query_parcels(
    db: Session,
    q: str | None = None,
    carrier: str | None = None,
    status: str | None = None,
    client_id: int | None = None,
    open_only: bool = False,
    days: int | None = None,
    limit: int = 1000,
    offset: int = 0,
):
    stmt = db.query(Parcel).options(joinedload(Parcel.client))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.filter(or_(
            Parcel.tracking_number.ilike(like),
            Parcel.client_reference.ilike(like),
            Parcel.description.ilike(like),
            Parcel.notes.ilike(like),
        ))
    if carrier and carrier != "all":
        stmt = stmt.filter(Parcel.carrier == carrier)
    if status == "open":
        stmt = stmt.filter(Parcel.status.in_(OPEN_STATUSES))
    elif status and status != "all":
        stmt = stmt.filter(Parcel.status == status)
    if client_id:
        stmt = stmt.filter(Parcel.client_id == client_id)
    if days:
        stmt = stmt.filter(Parcel.created_at >= utcnow() - timedelta(days=days))
    total = stmt.count()
    rows = (stmt.order_by(Parcel.status == "delivered", Parcel.updated_at.desc())
            .offset(offset).limit(limit).all())
    return rows, total


def parcel_to_dict(parcel: Parcel, include_events: bool = False) -> dict:
    data = {
        "id": parcel.id,
        "tracking_number": parcel.tracking_number,
        "carrier": parcel.carrier,
        "status": parcel.status,
        "status_text": parcel.status_text,
        "client_id": parcel.client_id,
        "client_name": parcel.client.name if parcel.client else "",
        "description": parcel.description,
        "client_reference": parcel.client_reference,
        "origin": parcel.origin,
        "destination": parcel.destination,
        "eta": parcel.eta.isoformat() if parcel.eta else None,
        "delivered_at": parcel.delivered_at.isoformat() if parcel.delivered_at else None,
        "last_event_at": parcel.last_event_at.isoformat() if parcel.last_event_at else None,
        "last_synced_at": parcel.last_synced_at.isoformat() if parcel.last_synced_at else None,
        "last_sync_error": parcel.last_sync_error,
        "cost_amount": parcel.cost_amount,
        "cost_currency": parcel.cost_currency,
        "weight_kg": parcel.weight_kg,
        "notes": parcel.notes,
        "barcode": parcel.barcode,
        "cartons_expected": parcel.cartons_expected or 1,
        "received_at": parcel.received_at.isoformat() if parcel.received_at else None,
        "received_by": parcel.received_by,
        "storage_location": parcel.storage_location,
        "released_at": parcel.released_at.isoformat() if parcel.released_at else None,
        "released_to": parcel.released_to,
        "released_by": parcel.released_by,
        "sync_enabled": parcel.sync_enabled,
        "share_token": parcel.share_token,
        "tracking_url": parcel.tracking_url,
        "days_in_transit": parcel.days_in_transit,
        "created_at": parcel.created_at.isoformat() if parcel.created_at else None,
    }
    if include_events:
        data["events"] = [event_to_dict(e) for e in sorted(parcel.events, key=lambda e: e.occurred_at, reverse=True)]
    return data


def event_to_dict(event: ParcelEvent) -> dict:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "status": event.status,
        "status_text": event.status_text,
        "location": event.location,
        "description": event.description,
        "source": event.source,
    }
