"""Database models for ParcelDesk."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- statuses
STATUSES = [
    "registered",       # tracking number created / label issued
    "picked_up",        # collected by carrier
    "received",         # physically received at your warehouse
    "in_transit",       # moving between hubs
    "customs",          # customs clearance / held
    "out_for_delivery", # on the van
    "delivered",
    "exception",        # delay, failed attempt, damage, address problem
    "returned",
    "cancelled",
    "unknown",
]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="operator")  # admin | operator | viewer
    phone: Mapped[str] = mapped_column(String(40), default="")          # E.164, e.g. +261340000000
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    reference_prefix: Mapped[str] = mapped_column(String(20), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    notify_client: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(300), default="")   # client portal login
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parcels: Mapped[list["Parcel"]] = relationship(back_populates="client")


class Parcel(Base):
    __tablename__ = "parcels"
    __table_args__ = (Index("ix_parcels_carrier_status", "carrier", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_number: Mapped[str] = mapped_column(String(120), index=True)
    carrier: Mapped[str] = mapped_column(String(20), default="dhl")   # dhl | fedex | aramex | manual
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)

    description: Mapped[str] = mapped_column(Text, default="")
    client_reference: Mapped[str] = mapped_column(String(120), default="")
    origin: Mapped[str] = mapped_column(String(120), default="")
    destination: Mapped[str] = mapped_column(String(120), default="")

    status: Mapped[str] = mapped_column(String(30), default="registered", index=True)
    status_text: Mapped[str] = mapped_column(String(300), default="")
    eta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_error: Mapped[str] = mapped_column(String(400), default="")

    cost_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_currency: Mapped[str] = mapped_column(String(8), default="MGA")
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    notes: Mapped[str] = mapped_column(Text, default="")
    barcode: Mapped[str] = mapped_column(String(120), default="")        # optional alternate barcode
    cartons_expected: Mapped[int] = mapped_column(Integer, default=1)    # partial shipments
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[str] = mapped_column(String(120), default="")
    storage_location: Mapped[str] = mapped_column(String(120), default="")  # shelf / bin
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_to: Mapped[str] = mapped_column(String(200), default="")
    released_by: Mapped[str] = mapped_column(String(120), default="")
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    client: Mapped[Client | None] = relationship(back_populates="parcels")
    receipts: Mapped[list["ReceiptLine"]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan", order_by="ReceiptLine.carton_no")
    events: Mapped[list["ParcelEvent"]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan", order_by="ParcelEvent.occurred_at"
    )

    @property
    def tracking_url(self) -> str:
        from .carriers import tracking_url_for
        return tracking_url_for(self.carrier, self.tracking_number)

    @property
    def days_in_transit(self) -> int:
        if not self.created_at:
            return 0
        end = self.delivered_at or utcnow()
        return max(0, (end - self.created_at).days)


class ParcelEvent(Base):
    __tablename__ = "parcel_events"
    __table_args__ = (UniqueConstraint("parcel_id", "event_hash", name="uq_event_dedupe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    status_text: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="api")   # api | manual | import
    event_hash: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parcel: Mapped[Parcel] = relationship(back_populates="events")


class ReceiptLine(Base):
    # One carton checked in - a shipment can arrive in several parts.
    __tablename__ = "receipt_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)
    carton_no: Mapped[int] = mapped_column(Integer, default=1)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    received_by: Mapped[str] = mapped_column(String(120), default="")
    storage_location: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(400), default="")

    parcel: Mapped[Parcel] = relationship(back_populates="receipts")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int | None] = mapped_column(ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="status_change")
    channel: Mapped[str] = mapped_column(String(12), default="email")   # email | whatsapp | sms | webhook
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    recipients: Mapped[str] = mapped_column(String(600), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="scheduler")  # scheduler | manual | startup
    parcels_checked: Mapped[int] = mapped_column(Integer, default=0)
    events_added: Mapped[int] = mapped_column(Integer, default=0)
    parcels_updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
