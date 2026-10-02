"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=6)
    role: str = "operator"
    phone: str = ""
    notify_email: bool = True
    notify_sms: bool = False


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=6)
    role: str | None = None
    phone: str | None = None
    notify_email: bool | None = None
    notify_sms: bool | None = None
    is_active: bool | None = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


# ----------------------------------------------------------------- parcels
class ParcelCreate(BaseModel):
    tracking_number: str
    carrier: str | None = None            # auto-detected when omitted
    client_id: int | None = None
    client_name: str | None = None        # created on the fly if it does not exist
    description: str = ""
    client_reference: str = ""
    origin: str = ""
    destination: str = ""
    cost_amount: float | None = None
    cost_currency: str = "MGA"
    weight_kg: float | None = None
    notes: str = ""
    barcode: str = ""
    storage_location: str = ""
    cartons_expected: int = 1
    eta: datetime | None = None
    sync_now: bool = True


class ParcelUpdate(BaseModel):
    carrier: str | None = None
    client_id: int | None = None
    description: str | None = None
    client_reference: str | None = None
    origin: str | None = None
    destination: str | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None
    weight_kg: float | None = None
    notes: str | None = None
    barcode: str | None = None
    storage_location: str | None = None
    cartons_expected: int | None = None
    eta: datetime | None = None
    sync_enabled: bool | None = None


class EventCreate(BaseModel):
    status: str
    occurred_at: datetime | None = None
    status_text: str = ""
    location: str = ""
    description: str = ""


class ImportRequest(BaseModel):
    text: str | None = None               # pasted list, one parcel per line
    rows: list[dict] | None = None        # pre-structured rows
    auto_create_clients: bool = True
    sync_now: bool = False


# ----------------------------------------------------------------- clients
class ClientCreate(BaseModel):
    name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    reference_prefix: str = ""
    notes: str = ""
    notify_client: bool = False
    notify_sms: bool = False


class ClientUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    reference_prefix: str | None = None
    notes: str | None = None
    notify_client: bool | None = None
    notify_sms: bool | None = None


class SettingsUpdate(BaseModel):
    company_name: str | None = None
    public_base_url: str | None = None
    alerts_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    stuck_customs_days: int | None = Field(default=None, ge=1, le=365)
    stuck_transit_days: int | None = Field(default=None, ge=1, le=365)
    daily_digest_hour: int | None = Field(default=None, ge=0, le=23)
    warehouse_stale_days: int | None = Field(default=None, ge=1, le=365)
    ofd_sync_enabled: bool | None = None
    ofd_sync_minutes: int | None = Field(default=None, ge=10, le=1440)


class TestEmailRequest(BaseModel):
    to: str | None = None


class TestMessageRequest(BaseModel):
    to: str | None = None
    text: str = "Test message from ParcelDesk — alerts are working."


class PortalLogin(BaseModel):
    email: str
    password: str


class PortalPassword(BaseModel):
    password: str = Field(min_length=6)


class PortalPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class ReleaseRequest(BaseModel):
    released_to: str = ""
    note: str = ""


class CartonRequest(BaseModel):
    storage_location: str = ""
    note: str = ""
    count: int = 1
