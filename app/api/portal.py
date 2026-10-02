"""Client portal: self-service logins for customers (separate from staff accounts)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Client, Parcel, User, utcnow
from ..schemas import PortalLogin, PortalPasswordChange
from ..security import (create_client_token, current_client, hash_password, require_operator,
                        verify_password)
from ..services.parcels import OPEN_STATUSES
from .public import public_parcel

router = APIRouter(prefix="/api/portal", tags=["client portal"])
admin_router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.post("/login")
def portal_login(payload: PortalLogin, db: Session = Depends(get_db)):
    """Clients sign in with the email address on their account."""
    email = (payload.email or "").strip().lower()
    client = None
    if email:
        client = db.query(Client).filter(Client.email.ilike(email)).first()
        if not client:
            # allow sign-in with the company name too
            client = db.query(Client).filter(Client.name.ilike(payload.email.strip())).first()
    if not client or not client.password_hash or not verify_password(payload.password,
                                                                    client.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    client.last_login_at = utcnow()
    db.commit()
    return {
        "token": create_client_token(client),
        "client": {"id": client.id, "name": client.name, "contact_name": client.contact_name,
                   "company_name": settings.company_name},
    }


@router.get("/me")
def portal_me(client: Client = Depends(current_client), db: Session = Depends(get_db)):
    parcels = db.query(Parcel).filter(Parcel.client_id == client.id).all()
    return {
        "client": {"id": client.id, "name": client.name, "contact_name": client.contact_name,
                   "email": client.email, "phone": client.phone},
        "company_name": settings.company_name,
        "open_count": sum(1 for p in parcels if p.status in OPEN_STATUSES),
        "total": len(parcels),
    }


@router.get("/parcels")
def portal_parcels(client: Client = Depends(current_client), db: Session = Depends(get_db)):
    parcels = (db.query(Parcel).filter(Parcel.client_id == client.id)
               .order_by(Parcel.created_at.desc()).limit(300).all())
    return {
        "company_name": settings.company_name,
        "client": {"name": client.name, "contact_name": client.contact_name},
        "open_count": sum(1 for p in parcels if p.status in OPEN_STATUSES),
        "parcels": [
            {**public_parcel(p),
             "storage_location": p.storage_location if p.received_at else "",
             "released_at": p.released_at.date().isoformat() if p.released_at else None}
            for p in parcels
        ],
    }


@router.post("/change-password")
def portal_change_password(payload: PortalPasswordChange, client: Client = Depends(current_client),
                           db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, client.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    client.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


# ------------------------------------------------- staff-side management
@admin_router.post("/{client_id}/password")
def set_client_password(client_id: int, payload: dict,
                        _: User = Depends(require_operator), db: Session = Depends(get_db)):
    """Give a client portal access (or reset the password)."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    password = (payload or {}).get("password") or ""
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if not (client.email or "").strip():
        raise HTTPException(400, "Add an email address to this client first — it is their login")
    client.password_hash = hash_password(password)
    db.commit()
    return {"ok": True, "login_email": client.email}


@admin_router.delete("/{client_id}/password")
def clear_client_password(client_id: int, _: User = Depends(require_operator),
                          db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    client.password_hash = ""
    db.commit()
    return {"ok": True}
