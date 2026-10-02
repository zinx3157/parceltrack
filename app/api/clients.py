"""Client (customer) accounts with per-client tracking portals."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Client, Parcel, User
from ..schemas import ClientCreate, ClientUpdate
from ..security import current_user, require_admin, require_operator
from ..services.parcels import parcel_to_dict

router = APIRouter(prefix="/api/clients", tags=["clients"])


def client_to_dict(client: Client, parcel_count: int | None = None) -> dict:
    data = {
        "id": client.id, "name": client.name, "contact_name": client.contact_name,
        "email": client.email, "phone": client.phone,
        "reference_prefix": client.reference_prefix, "notes": client.notes,
        "notify_client": client.notify_client, "notify_sms": client.notify_sms,
        "share_token": client.share_token,
        "portal_login": bool(client.password_hash),
        "last_login_at": client.last_login_at.isoformat() if client.last_login_at else None,
        "created_at": client.created_at.isoformat() if client.created_at else None,
        "portal_url": f"{settings.public_base_url}/portal/{client.share_token}" if client.share_token else None,
    }
    if parcel_count is not None:
        data["parcel_count"] = parcel_count
    return data


@router.get("")
def list_clients(q: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = db.query(Client)
    if q:
        like = f"%{q}%"
        stmt = stmt.filter(Client.name.ilike(like) | Client.contact_name.ilike(like) |
                           Client.email.ilike(like))
    clients = stmt.order_by(Client.name).all()
    counts = dict(db.query(Parcel.client_id, __import__("sqlalchemy").func.count(Parcel.id))
                  .group_by(Parcel.client_id).all())
    return [client_to_dict(c, counts.get(c.id, 0)) for c in clients]


@router.post("", status_code=201)
def create_client(payload: ClientCreate, _: User = Depends(require_operator),
                  db: Session = Depends(get_db)):
    if db.query(Client).filter(Client.name.ilike(payload.name.strip())).first():
        raise HTTPException(409, "A client with this name already exists")
    data = payload.model_dump()
    data["name"] = payload.name.strip()
    client = Client(**data)
    db.add(client)
    db.commit()
    return client_to_dict(client, 0)


@router.patch("/{client_id}")
def update_client(client_id: int, payload: ClientUpdate, _: User = Depends(require_operator),
                  db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    db.commit()
    return client_to_dict(client)


@router.delete("/{client_id}")
def delete_client(client_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    db.query(Parcel).filter(Parcel.client_id == client_id).update({"client_id": None})
    db.delete(client)
    db.commit()
    return {"ok": True}


@router.post("/{client_id}/portal")
def enable_portal(client_id: int, _: User = Depends(require_operator), db: Session = Depends(get_db)):
    """Create/return a read-only portal link the client can bookmark."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if not client.share_token:
        client.share_token = secrets.token_urlsafe(24)
        db.commit()
    return {"portal_url": f"{settings.public_base_url}/portal/{client.share_token}",
            "share_token": client.share_token}


@router.delete("/{client_id}/portal")
def disable_portal(client_id: int, _: User = Depends(require_operator), db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    client.share_token = None
    db.commit()
    return {"ok": True}


@router.get("/{client_id}/parcels")
def client_parcels(client_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "Client not found")
    parcels = (db.query(Parcel).filter(Parcel.client_id == client_id)
               .order_by(Parcel.created_at.desc()).all())
    return [parcel_to_dict(p) for p in parcels]
