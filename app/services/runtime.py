"""Runtime settings that admins can change from the UI (stored in the DB)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Setting

RUNTIME_KEYS: dict[str, type] = {
    "company_name": str,
    "public_base_url": str,
    "alerts_enabled": bool,
    "sync_interval_minutes": int,
    "stuck_customs_days": int,
    "stuck_transit_days": int,
    "daily_digest_hour": int,
    "warehouse_stale_days": int,
    "ofd_sync_enabled": bool,
    "ofd_sync_minutes": int,
}


def _cast(key: str, value):
    kind = RUNTIME_KEYS[key]
    if kind is bool:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if kind is int:
        return int(value)
    return str(value)


def load_overrides(db: Session) -> None:
    for row in db.query(Setting).all():
        if row.key in RUNTIME_KEYS:
            try:
                setattr(settings, row.key, _cast(row.key, row.value))
            except (ValueError, TypeError):
                continue


def set_setting(db: Session, key: str, value) -> None:
    if key not in RUNTIME_KEYS:
        raise KeyError(key)
    row = db.get(Setting, key)
    if row:
        row.value = str(value)
    else:
        db.add(Setting(key=key, value=str(value)))
    db.commit()
    setattr(settings, key, _cast(key, value))


def current_values() -> dict:
    return {key: getattr(settings, key) for key in RUNTIME_KEYS}
