"""Password hashing, JWT tokens and role-based access dependencies."""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Client, User

ALGO = "HS256"
_bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}


def hash_password(password: str, *, salt: str | None = None) -> str:
    """PBKDF2-SHA256, stdlib only (no native build dependencies)."""
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260_000).hex()
    return hmac.compare_digest(candidate, digest)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def _password_fingerprint(password_hash: str | None) -> str:
    """Short digest of the stored hash — lets a token die when the password changes."""
    digest = hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()
    return digest[:16]


def create_client_token(client: Client) -> str:
    # Portal session for a client (separate audience from staff tokens)
    payload = {
        "sub": str(client.id),
        "aud": "client",
        "name": client.name,
        "pv": _password_fingerprint(client.password_hash),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def current_client(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Client:
    token = creds.credentials if creds else request.cookies.get("parceldesk_client_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    payload = _decode(token)
    if payload.get("aud") != "client":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Staff accounts cannot use the client portal")
    client = db.get(Client, int(payload["sub"]))
    if not client:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Client account not found")
    if payload.get("pv") != _password_fingerprint(client.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Portal access changed — please sign in again")
    return client


def _decode(token: str) -> dict:
    try:
        # audience is checked by hand below: staff tokens have no "aud" claim while
        # portal tokens carry aud="client", and PyJWT rejects any aud it cannot
        # match against an expected audience.
        return jwt.decode(token, settings.secret_key, algorithms=[ALGO],
                          options={"verify_aud": False})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session token")


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    token = creds.credentials if creds else request.cookies.get("parceldesk_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = _decode(token)
    if payload.get("aud") == "client":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Client portal accounts cannot use the staff app")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return user


def require_role(minimum: str):
    """Dependency factory: require at least the given role."""
    def _dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum} role")
        return user
    return _dep


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")
