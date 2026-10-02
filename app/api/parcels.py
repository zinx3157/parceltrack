"""Parcel endpoints: CRUD, manual updates, sync, sharing, import and export."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException, Query,
                     Response, UploadFile)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..carriers import CARRIER_LABELS, detect_carrier, guess_carrier
from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Client, Parcel, User, utcnow
from ..schemas import EventCreate, ImportRequest, ParcelCreate, ParcelUpdate
from ..security import current_user, require_admin, require_operator
from ..services import importer, reports, tracking
from ..services.parcels import OPEN_STATUSES, parcel_to_dict, query_parcels

router = APIRouter(prefix="/api/parcels", tags=["parcels"])


def _get_parcel(db: Session, parcel_id: int) -> Parcel:
    parcel = db.get(Parcel, parcel_id)
    if not parcel:
        raise HTTPException(404, "Parcel not found")
    return parcel


def _resolve_client(db: Session, client_id: int | None, client_name: str | None) -> int | None:
    if client_id:
        if not db.get(Client, client_id):
            raise HTTPException(400, "Client not found")
        return client_id
    if client_name and client_name.strip():
        client = db.query(Client).filter(Client.name.ilike(client_name.strip())).first()
        if not client:
            client = Client(name=client_name.strip())
            db.add(client)
            db.flush()
        return client.id
    return None


@router.get("")
def list_parcels(
    q: str | None = None,
    carrier: str | None = None,
    status: str | None = None,
    client_id: int | None = None,
    days: int | None = None,
    limit: int = Query(200, le=2000),
    offset: int = 0,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows, total = query_parcels(db, q=q, carrier=carrier, status=status, client_id=client_id,
                                days=days, limit=limit, offset=offset)
    return {"total": total, "items": [parcel_to_dict(p) for p in rows]}


@router.get("/stats")
def parcel_stats(days: int = 30, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return reports.stats(db, days=days)


@router.get("/detect")
def detect(number: str, _: User = Depends(current_user)):
    candidates = detect_carrier(number)
    return {
        "tracking_number": number,
        "guess": candidates[0] if candidates else "manual",
        "candidates": [{"carrier": c, "label": CARRIER_LABELS.get(c, c)} for c in candidates] or
                      [{"carrier": "manual", "label": CARRIER_LABELS["manual"]}],
    }


@router.get("/export.xlsx")
def export_xlsx(
    q: str | None = None, carrier: str | None = None, status: str | None = None,
    client_id: int | None = None, _: User = Depends(current_user), db: Session = Depends(get_db),
):
    content = reports.export_xlsx(db, q=q, carrier=carrier, status=status, client_id=client_id)
    name = f"parcels_{utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/export.csv")
def export_csv(
    q: str | None = None, carrier: str | None = None, status: str | None = None,
    client_id: int | None = None, _: User = Depends(current_user), db: Session = Depends(get_db),
):
    content = reports.export_csv(db, q=q, carrier=carrier, status=status, client_id=client_id)
    name = f"parcels_{utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return Response(content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/import")
def import_parcels(payload: ImportRequest, background: BackgroundTasks,
                   user: User = Depends(require_operator), db: Session = Depends(get_db)):
    rows: list[dict] = []
    if payload.text:
        rows += importer.parse_text(payload.text)
    if payload.rows:
        rows += payload.rows
    if not rows:
        raise HTTPException(400, "Nothing to import — provide text or rows")
    summary = importer.rows_to_parcels(db, rows, created_by_id=user.id,
                                       auto_create_clients=payload.auto_create_clients)
    if payload.sync_now and summary["created"]:
        background.add_task(_background_sync_new, summary["created"])
    return summary


@router.post("/import/file")
async def import_file(background: BackgroundTasks, file: UploadFile = File(...),
                      auto_create_clients: bool = True, sync_now: bool = False,
                      user: User = Depends(require_operator), db: Session = Depends(get_db)):
    content = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            rows = importer.parse_xlsx_bytes(content)
        else:
            rows = importer.parse_csv_bytes(content)
    except Exception as exc:
        raise HTTPException(400, f"Could not read file: {exc}")
    if not rows:
        raise HTTPException(400, "No rows found in file")
    summary = importer.rows_to_parcels(db, rows, created_by_id=user.id,
                                       auto_create_clients=auto_create_clients)
    if sync_now and summary["created"]:
        background.add_task(_background_sync_new, summary["created"])
    return summary


def _background_sync_new(tracking_numbers: list[str]) -> None:
    db = SessionLocal()
    try:
        for tn in tracking_numbers:
            parcel = db.query(Parcel).filter(Parcel.tracking_number == tn).first()
            if parcel:
                try:
                    tracking.sync_parcel(db, parcel)
                except Exception:
                    db.rollback()
    finally:
        db.close()


@router.post("", status_code=201)
def create_parcel(payload: ParcelCreate, background: BackgroundTasks,
                  user: User = Depends(require_operator), db: Session = Depends(get_db)):
    tn = payload.tracking_number.strip()
    if not tn:
        raise HTTPException(400, "Tracking number is required")
    if db.query(Parcel.id).filter(Parcel.tracking_number == tn).first():
        raise HTTPException(409, f"Parcel {tn} is already tracked")

    carrier = (payload.carrier or "").strip().lower()
    if not carrier or carrier not in CARRIER_LABELS:
        carrier = guess_carrier(tn)

    parcel = Parcel(
        tracking_number=tn,
        carrier=carrier,
        client_id=_resolve_client(db, payload.client_id, payload.client_name),
        description=payload.description,
        client_reference=payload.client_reference,
        origin=payload.origin,
        destination=payload.destination,
        cost_amount=payload.cost_amount,
        cost_currency=payload.cost_currency or "MGA",
        weight_kg=payload.weight_kg,
        notes=payload.notes,
        barcode=payload.barcode,
        storage_location=payload.storage_location,
        cartons_expected=max(1, payload.cartons_expected or 1),
        eta=payload.eta,
        status="registered",
        status_text="Registered in ParcelDesk",
        created_by_id=user.id,
    )
    db.add(parcel)
    db.commit()

    tracking.add_event(db, parcel, occurred_at=utcnow(), status="registered",
                       status_text="Registered in ParcelDesk", source="manual")
    db.commit()

    if payload.sync_now and carrier != "manual":
        background.add_task(_sync_one_background, parcel.id)
    return parcel_to_dict(parcel)


def _sync_one_background(parcel_id: int, force: bool = True) -> None:
    from ..config import settings as cfg
    if cfg.demo_mode:
        # demo data is generated instantly, so run it inline-safe in the background task
        pass
    db = SessionLocal()
    try:
        parcel = db.get(Parcel, parcel_id)
        if parcel:
            tracking.sync_parcel(db, parcel, force=force)
    finally:
        db.close()


@router.get("/{parcel_id}")
def get_parcel(parcel_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    data = parcel_to_dict(parcel, include_events=True)
    from ..services.receiving import parcel_receiving_state
    state = parcel_receiving_state(db, parcel)
    data.update({k: state[k] for k in ("cartons_received", "cartons_outstanding", "complete",
                                       "cartons")})
    data["label_url"] = f"/labels/{parcel.id}"
    data["barcode_svg_url"] = f"/api/parcels/{parcel.id}/barcode.svg"
    data["client"] = ({"id": parcel.client.id, "name": parcel.client.name,
                       "email": parcel.client.email, "phone": parcel.client.phone}
                      if parcel.client else None)
    return data


@router.patch("/{parcel_id}")
def update_parcel(parcel_id: int, payload: ParcelUpdate,
                  _: User = Depends(require_operator), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("carrier") and data["carrier"] not in CARRIER_LABELS:
        raise HTTPException(400, "Unknown carrier")
    for field, value in data.items():
        setattr(parcel, field, value)
    db.commit()
    return parcel_to_dict(parcel)


@router.delete("/{parcel_id}")
def delete_parcel(parcel_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    db.delete(parcel)
    db.commit()
    return {"ok": True}


@router.post("/{parcel_id}/events", status_code=201)
def add_manual_event(parcel_id: int, payload: EventCreate,
                     _: User = Depends(require_operator), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    occurred = payload.occurred_at or utcnow()
    event = tracking.add_event(
        db, parcel, occurred_at=occurred, status=payload.status,
        status_text=payload.status_text or payload.description or payload.status,
        location=payload.location, description=payload.description, source="manual",
    )
    if not event:
        raise HTTPException(409, "This update already exists")
    old_status = parcel.status
    tracking.refresh_parcel_from_events(db, parcel)
    db.commit()
    if parcel.status != old_status:
        from ..services import alerts
        alerts.on_status_change(db, parcel, old_status, parcel.status)
    return parcel_to_dict(parcel, include_events=True)


@router.post("/{parcel_id}/sync")
def sync_parcel(parcel_id: int, force: bool = True,
                _: User = Depends(require_operator), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    result = tracking.sync_parcel(db, parcel, force=force)
    result["parcel"] = parcel_to_dict(parcel, include_events=True)
    return result


@router.post("/{parcel_id}/share")
def share_parcel(parcel_id: int, _: User = Depends(require_operator), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    if not parcel.share_token:
        parcel.share_token = secrets.token_urlsafe(24)
        db.commit()
    return {"share_token": parcel.share_token,
            "url": f"{settings.public_base_url}/track/{parcel.share_token}"}


@router.delete("/{parcel_id}/share")
def unshare_parcel(parcel_id: int, _: User = Depends(require_operator), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    parcel.share_token = None
    db.commit()
    return {"ok": True}


@router.post("/bulk/sync")
def bulk_sync(background: BackgroundTasks, limit: int = 200,
              _: User = Depends(require_operator), db: Session = Depends(get_db)):
    def _run():
        session = SessionLocal()
        try:
            tracking.sync_all(session, trigger="manual", limit=limit)
        finally:
            session.close()

    background.add_task(_run)
    return {"ok": True, "message": "Sync started in the background — refresh in a moment"}


@router.post("/{parcel_id}/remind")
def remind_client(parcel_id: int, _: User = Depends(require_operator), db: Session = Depends(get_db)):
    """Send the client (and internal team) a status email for this parcel."""
    parcel = _get_parcel(db, parcel_id)
    from ..services import alerts
    recipients = alerts._recipients_for(db, parcel)
    if not recipients:
        raise HTTPException(400, "No recipients configured for this parcel")
    subject = f"Update on your parcel {parcel.tracking_number} — {parcel.status_text[:60]}"
    body = "\n".join([
        f"Hello{(' ' + parcel.client.contact_name) if parcel.client and parcel.client.contact_name else ''},",
        "",
        f"Here is the latest on your shipment {parcel.tracking_number} ({parcel.carrier.upper()}):",
        f"Status : {parcel.status_text}",
        f"Location: {(parcel.events[-1].location if parcel.events else '') or '-'}",
        f"ETA    : {parcel.eta.date().isoformat() if parcel.eta else 'to be confirmed'}",
        "",
        f"Track online: {parcel.tracking_url}",
        "",
        settings.company_name,
    ])
    note = alerts._record(db, parcel=parcel, kind="manual_notice", subject=subject, body=body,
                          recipients=recipients)
    return {"ok": note.ok, "error": note.error, "recipients": recipients}
