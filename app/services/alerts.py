"""Email alerts: status changes, customs holds, daily digest.

Without SMTP credentials every alert is still recorded in the Notifications log
(visible in the app) so nothing is lost — it just isn't emailed.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Client, Notification, Parcel, User, utcnow

log = logging.getLogger("parceldesk.alerts")

STATUS_LABELS = {
    "registered": "Label created", "picked_up": "Picked up", "received": "Received at warehouse",
    "in_transit": "In transit",
    "customs": "In customs", "out_for_delivery": "Out for delivery", "delivered": "Delivered",
    "exception": "Exception", "returned": "Returned", "cancelled": "Cancelled", "unknown": "Update",
}


def _smtp_ready() -> bool:
    return bool(settings.alerts_enabled and settings.smtp_host)


def send_email(subject: str, body: str, recipients: list[str]) -> tuple[bool, str]:
    recipients = [r for r in {r.strip() for r in recipients if r and "@" in r}]
    if not recipients:
        return False, "no recipients"
    if not _smtp_ready():
        log.warning("SMTP not configured — alert not emailed: %s", subject)
        return False, "SMTP not configured (alert saved in the app log)"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    try:
        if settings.smtp_use_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            server.ehlo()
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                server.starttls()
                server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True, ""
    except Exception as exc:
        log.error("SMTP send failed: %s", exc)
        return False, str(exc)[:400]


def _recipients_for(db: Session, parcel: Parcel | None) -> list[str]:
    emails = [u.email for u in db.query(User).filter(User.is_active.is_(True),
                                                     User.notify_email.is_(True)).all()]
    if parcel and parcel.client and parcel.client.notify_client and parcel.client.email:
        emails.append(parcel.client.email)
    return emails


def _record(db: Session, *, parcel: Parcel | None, kind: str, subject: str, body: str,
            recipients: list[str], channel: str = "email") -> Notification:
    if channel == "email":
        ok, error = send_email(subject, body, recipients)
    else:  # WhatsApp / SMS / webhook handled by the messaging service
        from . import messaging
        results = messaging.send_text(body, recipients)
        ok = all(r["ok"] for r in results) if results else False
        error = "; ".join(r["error"] for r in results if r["error"])[:400]
    note = Notification(parcel_id=parcel.id if parcel else None, kind=kind, subject=subject,
                        body=body, recipients=",".join(recipients), ok=ok, error=error,
                        channel=channel)
    db.add(note)
    db.commit()
    return note


def on_status_change(db: Session, parcel: Parcel, old_status: str, new_status: str) -> None:
    """Called by the sync engine whenever a parcel changes status."""
    if new_status not in settings.alert_status_set:
        _maybe_text(db, parcel, old_status, new_status)
        return
    # rate-limit repeats of the same transition on the same parcel
    recent = (db.query(Notification)
              .filter(Notification.parcel_id == parcel.id, Notification.kind == new_status,
                      Notification.channel == "email",
                      Notification.created_at >= utcnow() - timedelta(hours=6))
              .first())
    if recent:
        _maybe_text(db, parcel, old_status, new_status)
        return

    client = f" for {parcel.client.name}" if parcel.client else ""
    subject = f"[{settings.company_name}] {parcel.tracking_number} — {STATUS_LABELS.get(new_status, new_status)}{client}"
    body = "\n".join([
        f"{parcel.carrier.upper()} parcel {parcel.tracking_number}{client}",
        f"New status : {STATUS_LABELS.get(new_status, new_status)} ({old_status} -> {new_status})",
        f"Latest     : {parcel.status_text}",
        f"Reference  : {parcel.client_reference or '-'}",
        f"Destination: {parcel.destination or '-'}",
        f"ETA        : {parcel.eta.date().isoformat() if parcel.eta else '-'}",
        "",
        f"Track: {parcel.tracking_url}",
        f"Open in ParcelDesk: {settings.public_base_url}",
    ])
    if settings.alerts_enabled:
        _record(db, parcel=parcel, kind=new_status, subject=subject, body=body,
                recipients=_recipients_for(db, parcel), channel="email")
    _maybe_text(db, parcel, old_status, new_status)


def _maybe_text(db: Session, parcel: Parcel, old_status: str, new_status: str) -> None:
    """Send a WhatsApp/SMS alert when the provider is set up and the status qualifies."""
    from . import messaging

    if not settings.messaging_enabled:
        return
    if new_status not in (settings.messaging_status_set or messaging.DEFAULT_STATUSES):
        return
    recent = (db.query(Notification)
              .filter(Notification.parcel_id == parcel.id, Notification.kind == new_status,
                      Notification.channel != "email",
                      Notification.created_at >= utcnow() - timedelta(hours=6))
              .first())
    if recent:
        return
    label = STATUS_LABELS.get(new_status, new_status)
    text = messaging.message_for(parcel, label)
    messaging.deliver(db, parcel=parcel, kind=new_status, text=text)


def notify_stuck(db: Session) -> int:
    """Customs holds / silent shipments — one alert every 3 days per parcel."""
    from .tracking import stuck_parcels

    sent = 0
    for item in stuck_parcels(db):
        parcel: Parcel = item["parcel"]
        recent = (db.query(Notification)
                  .filter(Notification.parcel_id == parcel.id, Notification.kind == item["kind"],
                          Notification.created_at >= utcnow() - timedelta(days=3))
                  .first())
        if recent:
            continue
        label = "in customs" if item["kind"] == "stuck_customs" else "with no movement"
        subject = f"[{settings.company_name}] Stuck {item['days']}d {label}: {parcel.tracking_number}"
        body = (f"Parcel {parcel.tracking_number} ({parcel.carrier.upper()}) has been {label} "
                f"for {item['days']} days.\nLatest: {parcel.status_text}\n"
                f"Client: {parcel.client.name if parcel.client else '-'}\n"
                f"Track: {parcel.tracking_url}")
        if settings.alerts_enabled:
            _record(db, parcel=parcel, kind=item["kind"], subject=subject, body=body,
                    recipients=_recipients_for(db, parcel), channel="email")
        if settings.messaging_enabled:
            from . import messaging
            text = (f"[{settings.company_name}] {parcel.tracking_number} "
                    f"{'blocked in customs' if item['kind'] == 'stuck_customs' else 'no movement'} "
                    f"for {item['days']} days — {parcel.status_text[:90]}")
            messaging.deliver(db, parcel=parcel, kind=item["kind"], text=text)
        sent += 1
    return sent


def daily_digest(db: Session) -> int:
    from .parcels import OPEN_STATUSES
    from .tracking import stuck_parcels

    open_parcels = db.query(Parcel).filter(Parcel.status.in_(OPEN_STATUSES)).all()
    stuck = {i["parcel"].id for i in stuck_parcels(db)}
    delivered_24h = (db.query(Parcel)
                     .filter(Parcel.delivered_at >= utcnow() - timedelta(days=1)).count())
    by_status: dict[str, int] = {}
    for p in open_parcels:
        by_status[p.status] = by_status.get(p.status, 0) + 1

    lines = [
        f"Daily parcel digest — {utcnow().date().isoformat()}",
        "",
        f"Open parcels   : {len(open_parcels)}",
        f"Delivered (24h): {delivered_24h}",
        f"Stuck flagged  : {len(stuck)}",
        "",
        "By status:",
    ]
    lines += [f"  - {STATUS_LABELS.get(k, k)}: {v}" for k, v in sorted(by_status.items())]
    if stuck:
        lines += ["", "Needs attention:"]
        lines += [f"  - {p.tracking_number} ({p.carrier.upper()}) {p.status_text}"
                  for p in open_parcels if p.id in stuck][:15]
    subject = f"[{settings.company_name}] {len(open_parcels)} open parcels, {len(stuck)} stuck"
    _record(db, parcel=None, kind="digest", subject=subject, body="\n".join(lines),
            recipients=_recipients_for(db, None), channel="email")
    if settings.messaging_enabled:
        from . import messaging
        text = (f"[{settings.company_name}] Daily: {len(open_parcels)} open parcels, "
                f"{delivered_24h} delivered in 24h, {len(stuck)} needing attention.")
        messaging.deliver(db, parcel=None, kind="digest", text=text)
    return len(open_parcels)
