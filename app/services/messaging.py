"""WhatsApp / SMS alerts.

Three providers, all outbound:

  whatsapp  Meta WhatsApp Cloud API  (graph.facebook.com)  — official WhatsApp Business
  twilio    Twilio Programmable SMS / WhatsApp            — SMS or WhatsApp via Twilio
  webhook   generic HTTP gateway                          — Africa's Talking, Vonage,
                                                             n8n, Zapier, your own bot…

Pick one with MESSAGING_PROVIDER in .env. When nothing is configured the platform keeps
working: alerts are still recorded in the in-app log (channel-tagged), just not sent.
"""
from __future__ import annotations

import json
import logging
import re

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Client, Notification, Parcel, User, utcnow

log = logging.getLogger("parceldesk.messaging")

# statuses that are worth a text message by default (override with MESSAGING_ALERT_STATUSES)
DEFAULT_STATUSES = {"delivered", "exception", "customs", "out_for_delivery"}
MAX_LEN = 700


def _clean_number(number: str) -> str:
    return re.sub(r"[^\d+]", "", (number or "").strip())


def provider_status() -> dict:
    """Which messaging channel is usable right now (powers the Settings screen)."""
    provider = (settings.messaging_provider or "none").strip().lower()
    missing: list[str] = []
    if provider == "whatsapp":
        if not settings.whatsapp_token:
            missing.append("WHATSAPP_TOKEN")
        if not settings.whatsapp_phone_id:
            missing.append("WHATSAPP_PHONE_ID")
    elif provider == "twilio":
        if not settings.twilio_account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not settings.twilio_auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not settings.twilio_from:
            missing.append("TWILIO_FROM")
    elif provider == "webhook":
        if not settings.webhook_url:
            missing.append("WEBHOOK_URL")
    elif provider != "none":
        missing.append(f"unknown provider '{provider}'")

    configured = bool(settings.messaging_enabled) and provider != "none" and not missing
    hint = ""
    if provider == "none":
        hint = ("Set MESSAGING_PROVIDER=whatsapp (Meta Cloud API), twilio (SMS/WhatsApp) "
                "or webhook (generic gateway) in .env, then restart ParcelDesk.")
    elif missing:
        hint = f"Add {', '.join(missing)} to .env and restart ParcelDesk."
    label = {"whatsapp": "WhatsApp (Meta Cloud API)", "twilio": "Twilio SMS/WhatsApp",
             "webhook": "HTTP gateway (webhook)", "none": "not configured"}.get(provider, provider)
    return {
        "enabled": settings.messaging_enabled,
        "provider": provider,
        "provider_label": label,
        "configured": configured,
        "missing": missing,
        "hint": hint,
        "use_whatsapp_on_twilio": settings.twilio_use_whatsapp,
        "fallback_recipients": settings.messaging_number_list,
        "alert_statuses": ",".join(sorted(settings.messaging_status_set)),
    }


# ------------------------------------------------------------------ senders
def _send_whatsapp(to: str, text: str) -> tuple[bool, str]:
    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_id}/messages"
    payload = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text",
               "text": {"body": text[:4096], "preview_url": False}}
    try:
        resp = httpx.post(url, json=payload, timeout=settings.http_timeout_seconds,
                          headers={"Authorization": f"Bearer {settings.whatsapp_token}"})
    except httpx.HTTPError as exc:
        return False, f"WhatsApp connection error: {exc}"
    if resp.status_code >= 400:
        try:
            err = (resp.json().get("error") or {}).get("message")
        except ValueError:
            err = resp.text[:200]
        return False, f"WhatsApp API {resp.status_code}: {err}"
    return True, ""


def _send_twilio(to: str, text: str) -> tuple[bool, str]:
    sid = settings.twilio_account_sid
    sender = settings.twilio_from
    recipient = to
    if settings.twilio_use_whatsapp:
        sender = sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}"
        recipient = recipient if recipient.startswith("whatsapp:") else f"whatsapp:{recipient}"
    try:
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": sender, "To": recipient, "Body": text[:1600]},
            auth=(sid, settings.twilio_auth_token),
            timeout=settings.http_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return False, f"Twilio connection error: {exc}"
    if resp.status_code >= 400:
        try:
            err = resp.json().get("message")
        except ValueError:
            err = resp.text[:200]
        return False, f"Twilio API {resp.status_code}: {err}"
    return True, ""


def _send_webhook(to: str, text: str) -> tuple[bool, str]:
    payload: dict
    if settings.webhook_payload_template:
        try:
            rendered = settings.webhook_payload_template.replace("{to}", to).replace(
                "{message}", text.replace('"', "'")[:600])
            payload = json.loads(rendered)
        except (ValueError, TypeError):
            payload = {"to": to, "message": text}
    else:
        payload = {"to": to, "message": text, "sender": settings.company_name}
    headers = {"Content-Type": "application/json"}
    if settings.webhook_token:
        headers["Authorization"] = f"Bearer {settings.webhook_token}"
    try:
        resp = httpx.post(settings.webhook_url, json=payload, headers=headers,
                          timeout=settings.http_timeout_seconds)
    except httpx.HTTPError as exc:
        return False, f"Webhook connection error: {exc}"
    if resp.status_code >= 400:
        return False, f"Webhook HTTP {resp.status_code}: {resp.text[:200]}"
    return True, ""


def channels_available() -> list[str]:
    """Which channel ids the current provider can reach."""
    provider = (settings.messaging_provider or "none").strip().lower()
    if not settings.messaging_enabled:
        return []
    if provider == "twilio":
        return ["whatsapp" if settings.twilio_use_whatsapp else "sms"]
    if provider == "whatsapp":
        return ["whatsapp"]
    if provider == "webhook":
        return ["webhook"]
    return []


def send_text(text: str, numbers: list[str]) -> list[dict]:
    """Send one message to every number. Returns a per-recipient result list."""
    status = provider_status()
    provider = status["provider"]
    results: list[dict] = []
    for number in numbers:
        clean = _clean_number(number)
        if not clean or "@" in (number or ""):
            continue
        if not status["configured"]:
            reason = "; ".join(status["missing"]) or status.get("hint") or "messaging not configured"
            results.append({"to": clean, "ok": False, "channel": provider, "error": reason})
            continue
        if provider == "whatsapp":
            ok, error = _send_whatsapp(clean, text)
            channel = "whatsapp"
        elif provider == "twilio":
            ok, error = _send_twilio(clean, text)
            channel = "whatsapp" if settings.twilio_use_whatsapp else "sms"
        else:
            ok, error = _send_webhook(clean, text)
            channel = "webhook"
        if not ok:
            log.warning("Message to %s failed: %s", clean, error)
        results.append({"to": clean, "ok": ok, "channel": channel, "error": error})
    return results


# -------------------------------------------------------------- recipients
def recipients_for(db: Session, parcel: Parcel | None) -> list[str]:
    """Team members who opted into texts, plus the client when enabled."""
    numbers = [u.phone for u in db.query(User).filter(
        User.is_active.is_(True), User.notify_sms.is_(True)).all() if u.phone]
    if parcel and parcel.client and parcel.client.notify_sms and parcel.client.phone:
        numbers.append(parcel.client.phone)
    return numbers or settings.messaging_number_list


def message_for(parcel: Parcel, status_label: str) -> str:
    """Short, courier-style text message."""
    client = f" ({parcel.client.name})" if parcel.client else ""
    eta = f" ETA {parcel.eta.date().isoformat()}" if parcel.eta else ""
    parts = [
        f"[{settings.company_name}] {parcel.tracking_number}{client}",
        f"{parcel.carrier.upper()}: {status_label}",
    ]
    if parcel.status_text:
        parts.append(parcel.status_text[:120])
    if eta and status_label.lower() not in ("delivered", "livré"):
        parts.append(eta.strip())
    if parcel.tracking_url and status_label.lower() == "delivered":
        parts.append(parcel.tracking_url)
    return "\n".join(parts)[:MAX_LEN]


def deliver(db: Session, *, parcel: Parcel | None, kind: str, text: str,
            numbers: list[str] | None = None) -> list[Notification]:
    """Send a message and record one log entry per recipient."""
    numbers = numbers if numbers is not None else recipients_for(db, parcel)
    status = provider_status()
    channel = (channels_available() or ["none"])[0]
    if not numbers:
        note = Notification(parcel_id=parcel.id if parcel else None, kind=kind, channel=channel,
                            subject=text.splitlines()[0][:200], body=text,
                            recipients="", ok=False, error="no phone numbers configured")
        db.add(note)
        db.commit()
        return [note]

    results = send_text(text, numbers)
    notes: list[Notification] = []
    for result in results:
        note = Notification(
            parcel_id=parcel.id if parcel else None, kind=kind, channel=result["channel"],
            subject=text.splitlines()[0][:200], body=text, recipients=result["to"],
            ok=result["ok"], error=result["error"][:400],
        )
        db.add(note)
        notes.append(note)
    db.commit()
    if not status["configured"]:
        log.info("Messaging not configured — %s alert recorded in the in-app log", kind)
    return notes
