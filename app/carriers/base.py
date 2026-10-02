"""Shared types + status normalisation used by every carrier adapter."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TrackEvent:
    occurred_at: datetime
    status: str              # normalised status (see models.STATUSES)
    status_text: str = ""    # raw carrier wording
    location: str = ""
    description: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class TrackResult:
    ok: bool
    events: list[TrackEvent] = field(default_factory=list)
    eta: datetime | None = None
    error: str = ""
    raw: dict | None = None


# ------------------------------------------------------------------ dates
def parse_dt(value) -> datetime | None:
    """Parse ISO strings, '/Date(1712345678900)/' and date-only values into naive UTC."""
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value) / (1000 if value > 1e11 else 1), tz=timezone.utc)
    else:
        text = str(value).strip()
        m = re.search(r"/Date\((-?\d+)", text)
        if m:
            dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
        else:
            text = text.replace("Z", "+00:00")
            # DHL sometimes returns "2024-05-01T10:00:00" with a separate offset field
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%m/%d/%Y"):
                    try:
                        dt = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ------------------------------------------------------------- status map
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("delivered", ("delivered", "signed for", "delivery completed", "shipment delivered",
                   "pod", "proof of delivery", "completed delivery",
                   "livré", "livraison effectuée", "remis au destinataire", "colis livré")),
    ("out_for_delivery", ("out for delivery", "with delivery courier", "on vehicle for delivery",
                          "courier is on the way", "being delivered", "delivery courier",
                          "en cours de livraison", "en livraison", "prêt à être livré")),
    ("returned", ("returned to sender", "return to shipper", "returned to shipper", "rts",
                  "return shipment", "returned undelivered", "retour à l'expéditeur",
                  "retourné à l'expéditeur")),
    ("cancelled", ("cancelled", "canceled", "shipment voided", "voided", "annulé")),
    ("customs", ("customs", "clearance", "duty", "duties", "held at destination",
                 "held in customs", "import processing", "agency review",
                 "douane", "dédouanement", "dedouanement", "en cours de dédouanement")),
    ("exception", ("exception", "delay", "delayed", "failed", "attempt", "damage", "damaged",
                   "lost", "refused", "address", "rescheduled", "unable to deliver", "weather",
                   "hold", "on hold", "problem", "delay in delivery",
                   "retard", "échec", "echec", "absent", "avarie", "non distribué",
                   "en attente", "bloqué", "suspendu", "refusé")),
    ("picked_up", ("picked up", "picked-up", "collected", "shipment picked", "picked",
                   "pris en charge", "collecté")),
    ("registered", ("label created", "shipment information received", "shipment data received",
                    "order data transmitted", "shipment details received", "booking",
                    "registered", "pre-transit", "information sent", "waybill created",
                    "colis annoncé", "préparation", "information reçue")),
    ("in_transit", ("transit", "arrived", "departed", "processed", "sorted", "forwarded",
                    "in the network", "at hub", "transferred", "loaded", "clearance completed",
                    "left", "received at", "flight", "manifest",
                    "en cours d'acheminement", "acheminement", "centre de tri", "départ",
                    "arrivée", "en transit")),
]

_FEDEX_CODES = {
    "DL": "delivered", "OD": "out_for_delivery", "IT": "in_transit", "PU": "picked_up",
    "OC": "registered", "AR": "in_transit", "AF": "in_transit", "DP": "in_transit",
    "SF": "in_transit", "CC": "in_transit", "RS": "returned", "CA": "cancelled",
    "DE": "delivered", "EX": "exception", "HL": "exception", "SE": "exception",
    "DY": "exception", "LD": "out_for_delivery", "CP": "customs",
}

_UPS_TYPES = {
    "D": "delivered", "I": "in_transit", "X": "exception", "P": "picked_up",
    "M": "registered", "O": "out_for_delivery", "RS": "returned", "DO": "in_transit",
    "MV": "in_transit", "NA": "unknown", "U": "unknown",
}

_STAGE_CODES = {
    "delivered": "delivered", "intransit": "in_transit", "pickup": "picked_up",
    "undelivered": "exception", "exception": "exception", "expired": "exception",
    "inforeceived": "registered",
}

_DHL_CODES = {
    "delivered": "delivered", "transit": "in_transit", "pre-transit": "registered",
    "failure": "exception", "unknown": "unknown", "customs": "customs",
}


def normalize_status(*texts: str | None, code: str | None = None) -> str:
    """Map a carrier status code / wording onto our normalised status list."""
    if code:
        c = code.strip().upper()
        if c in _FEDEX_CODES:
            return _FEDEX_CODES[c]
        if c in _UPS_TYPES:
            return _UPS_TYPES[c]
        low = code.strip().lower().replace(" ", "")
        if low in _DHL_CODES:
            return _DHL_CODES[low]
        if low in _STAGE_CODES:
            return _STAGE_CODES[low]

    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return "unknown"
    for status, keys in _KEYWORDS:
        if any(k in blob for k in keys):
            return status
    return "unknown"


class BaseAdapter:
    """Every carrier adapter exposes: name, configured, track()."""
    name: str = "base"

    def __init__(self, settings):  # noqa: D401
        self.settings = settings

    @property
    def configured(self) -> bool:
        return False

    def missing_config(self) -> list[str]:
        return []

    def track(self, tracking_number: str, parcel=None) -> TrackResult:  # pragma: no cover
        raise NotImplementedError
