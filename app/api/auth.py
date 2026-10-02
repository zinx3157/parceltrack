"""Authentication, current user and user administration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import ChangePassword, LoginRequest, UserCreate, UserUpdate
from ..security import (create_token, current_user, hash_password, require_admin,
                        verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])

VALID_ROLES = {"admin", "operator", "viewer"}


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.strip().lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled")
    return {
        "token": create_token(user),
        "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role,
                 "phone": user.phone, "notify_sms": user.notify_sms},
    }


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role,
            "phone": user.phone, "notify_email": user.notify_email, "notify_sms": user.notify_sms}


@router.post("/change-password")
def change_password(payload: ChangePassword, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


@users_router.get("")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [
        {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "phone": u.phone,
         "notify_email": u.notify_email, "notify_sms": u.notify_sms, "is_active": u.is_active,
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in db.query(User).order_by(User.id).all()
    ]


@users_router.post("", status_code=201)
def create_user(payload: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(VALID_ROLES)}")
    if db.query(User).filter(func.lower(User.email) == payload.email.strip().lower()).first():
        raise HTTPException(409, "A user with this email already exists")
    user = User(email=payload.email.strip().lower(), name=payload.name,
                password_hash=hash_password(payload.password), role=payload.role,
                phone=payload.phone, notify_email=payload.notify_email,
                notify_sms=payload.notify_sms)
    db.add(user)
    db.commit()
    return {"id": user.id}


@users_router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in VALID_ROLES:
        raise HTTPException(400, "Invalid role")
    if data.get("role") and user.id == admin.id and data["role"] != "admin":
        raise HTTPException(400, "You cannot remove your own admin role")
    if "password" in data and data["password"]:
        user.password_hash = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    return {"ok": True}
