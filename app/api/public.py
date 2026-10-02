"""Public, token-protected read-only views (no login required)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Client, Parcel
from ..services.parcels import OPEN_STATUSES, event_to_dict

router = APIRouter(tags=["public"])

STATUS_LABELS = {
    "registered": "Label created", "picked_up": "Picked up", "received": "Received at warehouse",
    "in_transit": "In transit",
    "customs": "In customs", "out_for_delivery": "Out for delivery", "delivered": "Delivered",
    "exception": "Exception — action needed", "returned": "Returned to sender",
    "cancelled": "Cancelled", "unknown": "Update received",
}


def public_parcel(parcel: Parcel) -> dict:
    return {
        "company_name": settings.company_name,
        "tracking_number": parcel.tracking_number,
        "carrier": parcel.carrier,
        "status": parcel.status,
        "status_label": STATUS_LABELS.get(parcel.status, parcel.status),
        "status_text": parcel.status_text,
        "description": parcel.description,
        "client_reference": parcel.client_reference,
        "origin": parcel.origin,
        "destination": parcel.destination,
        "eta": parcel.eta.date().isoformat() if parcel.eta else None,
        "delivered_at": parcel.delivered_at.date().isoformat() if parcel.delivered_at else None,
        "tracking_url": parcel.tracking_url,
        "events": [event_to_dict(e) for e in sorted(parcel.events,
                                                    key=lambda e: e.occurred_at, reverse=True)],
    }


@router.get("/api/public/track/{token}")
def track_by_token(token: str, db: Session = Depends(get_db)):
    parcel = db.query(Parcel).filter(Parcel.share_token == token).first()
    if not parcel:
        raise HTTPException(404, "This tracking link is no longer valid")
    return public_parcel(parcel)


@router.get("/api/public/client/{token}")
def client_portal_data(token: str, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.share_token == token).first()
    if not client:
        raise HTTPException(404, "This portal link is no longer valid")
    parcels = (db.query(Parcel).filter(Parcel.client_id == client.id)
               .order_by(Parcel.created_at.desc()).limit(300).all())
    return {
        "company_name": settings.company_name,
        "client": {"name": client.name, "contact_name": client.contact_name},
        "open_count": sum(1 for p in parcels if p.status in OPEN_STATUSES),
        "parcels": [public_parcel(p) for p in parcels],
    }
