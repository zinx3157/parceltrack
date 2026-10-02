"""Reporting: KPIs, Excel/CSV exports and printable client statements."""
from __future__ import annotations

import csv
import io
from datetime import timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Parcel, utcnow
from .parcels import OPEN_STATUSES, query_parcels

EXPORT_COLUMNS = [
    ("tracking_number", "Tracking number"), ("carrier", "Carrier"), ("status", "Status"),
    ("status_text", "Latest update"), ("client_name", "Client"), ("client_reference", "Reference"),
    ("description", "Description"), ("origin", "Origin"), ("destination", "Destination"),
    ("eta", "ETA"), ("last_event_at", "Last event"), ("delivered_at", "Delivered"),
    ("days_in_transit", "Days in transit"), ("cost_amount", "Cost"), ("cost_currency", "Currency"),
    ("weight_kg", "Weight (kg)"), ("received_at", "Received at"), ("received_by", "Received by"),
    ("storage_location", "Storage location"), ("barcode", "Barcode"),
    ("cartons_expected", "Cartons expected"), ("released_at", "Released at"),
    ("released_to", "Released to"),
    ("notes", "Notes"), ("tracking_url", "Tracking link"),
]


def stats(db: Session, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    total = db.query(func.count(Parcel.id)).scalar() or 0
    open_count = db.query(func.count(Parcel.id)).filter(Parcel.status.in_(OPEN_STATUSES)).scalar() or 0
    delivered = db.query(func.count(Parcel.id)).filter(Parcel.status == "delivered").scalar() or 0
    delivered_period = (db.query(func.count(Parcel.id))
                        .filter(Parcel.status == "delivered", Parcel.delivered_at >= since).scalar() or 0)
    exceptions = db.query(func.count(Parcel.id)).filter(Parcel.status == "exception").scalar() or 0
    customs = db.query(func.count(Parcel.id)).filter(Parcel.status == "customs").scalar() or 0
    out_for_delivery = (db.query(func.count(Parcel.id))
                        .filter(Parcel.status == "out_for_delivery").scalar() or 0)
    added_period = db.query(func.count(Parcel.id)).filter(Parcel.created_at >= since).scalar() or 0

    by_carrier = [
        {"carrier": carrier or "manual", "total": t, "open": o or 0, "delivered": d or 0}
        for carrier, t, o, d in db.query(
            Parcel.carrier,
            func.count(Parcel.id),
            func.sum(case((Parcel.status.in_(OPEN_STATUSES), 1), else_=0)),
            func.sum(case((Parcel.status == "delivered", 1), else_=0)),
        ).group_by(Parcel.carrier).all()
    ]

    by_status = [
        {"status": status or "unknown", "count": count}
        for status, count in db.query(Parcel.status, func.count(Parcel.id))
        .group_by(Parcel.status).all()
    ]

    # average transit time for parcels delivered in the window
    delivered_rows = (db.query(Parcel.created_at, Parcel.delivered_at)
                      .filter(Parcel.status == "delivered", Parcel.delivered_at.is_not(None)).all())
    durations = [(d - c).total_seconds() / 86400 for c, d in delivered_rows if c and d and d >= c]
    avg_transit = round(sum(durations) / len(durations), 1) if durations else None

    on_time = (db.query(func.count(Parcel.id))
               .filter(Parcel.status == "delivered", Parcel.eta.is_not(None),
                       Parcel.delivered_at <= Parcel.eta).scalar() or 0)
    with_eta = (db.query(func.count(Parcel.id))
                .filter(Parcel.status == "delivered", Parcel.eta.is_not(None)).scalar() or 0)

    from .tracking import stuck_parcels
    stuck = len(stuck_parcels(db))

    return {
        "total": total, "open": open_count, "delivered": delivered,
        "delivered_period": delivered_period, "added_period": added_period,
        "exceptions": exceptions, "in_customs": customs, "out_for_delivery": out_for_delivery,
        "stuck": stuck, "avg_transit_days": avg_transit,
        "on_time_pct": round(100 * on_time / with_eta) if with_eta else None,
        "by_carrier": sorted(by_carrier, key=lambda r: -(r["total"] or 0)),
        "by_status": sorted(by_status, key=lambda r: -r["count"]),
        "window_days": days,
    }


def _rows(db: Session, **filters) -> list[dict]:
    parcels, _ = query_parcels(db, limit=100000, **filters)
    from .parcels import parcel_to_dict
    return [parcel_to_dict(p) for p in parcels]


def export_xlsx(db: Session, **filters) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Parcels"
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True)

    for col, (_, label) in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = max(12, min(34, len(label) + 6))

    for row_idx, item in enumerate(_rows(db, **filters), start=2):
        for col, (key, _) in enumerate(EXPORT_COLUMNS, start=1):
            value = item.get(key)
            if isinstance(value, str) and len(value) > 300:
                value = value[:300]
            ws.cell(row=row_idx, column=col, value=value)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 20

    summary = wb.create_sheet("Summary")
    data = stats(db)
    summary.append(["ParcelDesk export", utcnow().strftime("%Y-%m-%d %H:%M")])
    summary.append([])
    for key in ("total", "open", "delivered", "in_customs", "exceptions", "stuck",
                "avg_transit_days", "on_time_pct"):
        summary.append([key.replace("_", " ").title(), data.get(key)])
    summary.append([])
    summary.append(["By carrier", "Total", "Open", "Delivered"])
    for row in data["by_carrier"]:
        summary.append([row["carrier"].upper(), row["total"], row["open"], row["delivered"]])
    summary.column_dimensions["A"].width = 22
    summary["A1"].font = Font(bold=True, size=13)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_csv(db: Session, **filters) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for item in _rows(db, **filters):
        writer.writerow([item.get(key, "") for key, _ in EXPORT_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")
