"""Seed data: first admin account + (optionally) demo clients and parcels."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .config import settings
from .models import Client, Parcel, ReceiptLine, User, utcnow
from .security import hash_password

log = logging.getLogger("parceldesk.seed")

DEMO_CLIENTS = [
    ("Société Mada Import", "Hery Rakoto", "hery@madaimport.mg", "+261 34 12 345 67", "MAD"),
    ("Pharma Océan Indien", "Dr. Rasoa", "logistics@pharma-oi.mg", "+261 33 45 678 90", "POI"),
    ("Tech Distri Tana", "Naina Andria", "naina@techdistri.mg", "+261 32 11 223 34", "TDT"),
    ("Boutique Vanille Co", "Lalao R.", "lalao@vanilleco.mg", "+261 34 98 765 43", "VCO"),
]

DEMO_PARCELS = [
    # (tracking, carrier, client index, description, origin, reference, weight, cost)
    ("1234567890", "dhl", 0, "Spare parts (2 cartons)", "Paris (CDG), FR", "INV-2026-118", 12.5, 850000),
    ("4567890123", "aramex", 1, "Pharmaceutical samples", "Dubai (DXB), AE", "POI-4471", 4.2, 420000),
    ("771234567890", "fedex", 2, "Laptop accessories", "Shenzhen (SZX), CN", "TDT-8890", 22.0, 1450000),
    ("9876543210", "dhl", 3, "Vanilla packaging", "Antananarivo (TNR), MG", "VCO-221", 8.0, 260000),
    ("5522334455", "aramex", 0, "Machine components", "Istanbul (IST), TR", "INV-2026-121", 35.4, 2100000),
    ("789123456789", "fedex", 1, "Lab equipment", "London (LHR), GB", "POI-4488", 18.9, 1750000),
    ("3344556677", "dhl", 2, "Phone cases (bulk)", "Guangzhou (CAN), CN", "TDT-8901", 41.0, 1980000),
    ("1Z999AA10123456784", "ups", 2, "Server rack parts", "Memphis (MEM), US", "TDT-8915", 28.7, 2450000),
    ("CL123456789FR", "colissimo", 3, "Perfume bottles (samples)", "Lyon (LYS), FR", "VCO-233", 3.5, 310000),
    ("RX123456789DE", "dhlecom", 0, "Spare connectors (small packet)", "Leipzig (LEJ), DE", "INV-2026-125", 1.8, 180000),
    ("EE123456789CN", "track17", 1, "Diagnostic reagents (EMS)", "Shanghai (PVG), CN", "POI-4492", 6.4, 640000),
]


def ensure_admin(db: Session) -> User:
    admin = db.query(User).filter(User.role == "admin").first()
    if admin:
        return admin
    admin = User(email=settings.first_admin_email.lower(), name="Administrator",
                 password_hash=hash_password(settings.first_admin_password), role="admin")
    db.add(admin)
    db.commit()
    log.warning("Created first admin account: %s (password from FIRST_ADMIN_PASSWORD)", admin.email)
    return admin


def seed_demo_data(db: Session, force: bool = False) -> dict:
    """Populate a realistic demo dataset so the app is explorable before go-live."""
    if db.query(Parcel.id).first() and not force:
        return {"created": 0, "message": "Parcels already exist — demo seed skipped"}

    admin = ensure_admin(db)
    clients = []
    for name, contact, email, phone, prefix in DEMO_CLIENTS:
        client = db.query(Client).filter(Client.name == name).first()
        if not client:
            client = Client(name=name, contact_name=contact, email=email, phone=phone,
                            reference_prefix=prefix, notify_client=False)
            db.add(client)
            db.flush()
        clients.append(client)

    rng = random.Random(7)
    now = utcnow()
    for idx, (tn, carrier, cidx, desc, origin, ref, weight, cost) in enumerate(DEMO_PARCELS):
        if db.query(Parcel.id).filter(Parcel.tracking_number == tn).first():
            continue
        age_days = rng.choice([1, 2, 3, 5, 8, 12])
        parcel = Parcel(
            tracking_number=tn, carrier=carrier, client_id=clients[cidx].id,
            description=desc, origin=origin, destination="Antananarivo (TNR), MG",
            client_reference=ref, weight_kg=weight, cost_amount=cost, cost_currency="MGA",
            status="registered", status_text="Registered in ParcelDesk",
            created_by_id=admin.id,
            created_at=now - timedelta(days=age_days),
        )
        db.add(parcel)
        db.flush()
        _seed_events(db, parcel, age_days)

    # a few parcels already checked in at the warehouse, so the Stock screen has content:
    # (tracking, location, cartons expected, cartons received, days on the shelf)
    shelved = [
        ("1234567890", "Rack A1 — Bin 3", 1, 1, 1),
        ("5522334455", "Rack C2 — Pallet 1", 3, 3, 4),      # complete — ready to release
        ("789123456789", "Cold room — Shelf 2", 2, 1, 11),  # partial + ageing over the limit
    ]
    for tn, location, expected, received, on_shelf in shelved:
        parcel = db.query(Parcel).filter(Parcel.tracking_number == tn).first()
        if not parcel or parcel.received_at:
            continue
        parcel.cartons_expected = expected
        parcel.received_at = utcnow() - timedelta(days=on_shelf)
        parcel.received_by = "Administrator"
        parcel.storage_location = location
        for carton_no in range(1, received + 1):
            db.add(ReceiptLine(
                parcel_id=parcel.id, carton_no=carton_no,
                received_at=parcel.received_at + timedelta(minutes=carton_no * 7),
                received_by=parcel.received_by, storage_location=location,
                note="Demo receipt" if carton_no == received else "",
            ))

    # a demo client login so the customer portal can be tried immediately
    demo_login = db.query(Client).filter(Client.email == "logistics@pharma-oi.mg").first()
    if demo_login and not demo_login.password_hash:
        demo_login.password_hash = hash_password("client123")
        log.info("Demo client portal login: %s / client123", demo_login.email)

    db.commit()
    return {"created": len(DEMO_PARCELS), "clients": len(clients)}


def _seed_events(db: Session, parcel: Parcel, age_days: int) -> None:
    """Attach a plausible timeline so the dashboard looks alive without API calls."""
    from .services import tracking

    rng = random.Random(hash(parcel.tracking_number) & 0xFFFF)
    start = parcel.created_at
    stage = rng.choice(["delivered", "delivered", "in_transit", "customs", "out_for_delivery"])

    plan = [("registered", "Shipment information received", parcel.origin)]
    if age_days >= 1:
        plan.append(("picked_up", "Shipment picked up", parcel.origin))
    if age_days >= 2:
        plan.append(("in_transit", "Processed at transit hub", "Nairobi (NBO), KE"))
    if age_days >= 3:
        plan.append(("in_transit", "Arrived at destination country", "Antananarivo (TNR), MG"))
    if age_days >= 4:
        plan.append(("customs", "Customs clearance status updated", "Antananarivo (TNR), MG"))
    if stage in ("out_for_delivery", "delivered") and age_days >= 5:
        plan.append(("customs", "Customs clearance processing complete", "Antananarivo (TNR), MG"))
        plan.append(("out_for_delivery", "Shipment is out for delivery", "Antananarivo (TNR), MG"))
    if stage == "delivered" and age_days >= 6:
        plan.append(("delivered", f"Delivered - Signed for by {rng.choice(['RASOA','RAKOTO','ANDRIAN'])}",
                     "Antananarivo (TNR), MG"))

    for i, (status, text, location) in enumerate(plan):
        occurred = start + timedelta(days=i * (age_days / max(1, len(plan))), hours=rng.randint(1, 9))
        if occurred > utcnow():
            occurred = utcnow() - timedelta(hours=1)
        tracking.add_event(db, parcel, occurred_at=occurred, status=status, status_text=text,
                           location=location, source="import", raw={"seeded": True})
    tracking.refresh_parcel_from_events(db, parcel)
    if stage == "delivered":
        parcel.eta = parcel.delivered_at
    else:
        parcel.eta = utcnow() + timedelta(days=rng.randint(1, 6))
    parcel.last_synced_at = utcnow()
