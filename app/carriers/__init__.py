"""Carrier registry: adapter lookup, tracking-number detection, public URLs."""
from __future__ import annotations

import re

from ..config import settings as default_settings
from .aramex import AramexAdapter
from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt
from .colissimo import ColissimoAdapter
from .demo import DemoAdapter
from .dhl import DHLAdapter
from .dhlecom import DHLeCommerceAdapter
from .fedex import FedExAdapter
from .manual import ManualAdapter
from .track17 import Track17Adapter
from .ups import UPSAdapter

CARRIERS = ["dhl", "fedex", "aramex", "ups", "dhlecom", "colissimo", "track17", "manual"]

CARRIER_LABELS = {
    "dhl": "DHL Express",
    "fedex": "FedEx",
    "aramex": "Aramex",
    "ups": "UPS",
    "dhlecom": "DHL eCommerce / Parcel",
    "colissimo": "Colissimo / La Poste",
    "track17": "17TRACK (EMS, postal, other)",
    "manual": "Manual / Other",
}

CARRIER_ABBR = {"dhl": "DHL", "fedex": "FX", "aramex": "ARX", "ups": "UPS",
                "dhlecom": "DHe", "colissimo": "COL", "track17": "17T", "manual": "—"}

_REAL: dict[str, type[BaseAdapter]] = {
    "dhl": DHLAdapter,
    "fedex": FedExAdapter,
    "aramex": AramexAdapter,
    "ups": UPSAdapter,
    "dhlecom": DHLeCommerceAdapter,
    "colissimo": ColissimoAdapter,
    "track17": Track17Adapter,
    "manual": ManualAdapter,
}


def get_adapter(carrier: str, settings=None) -> BaseAdapter:
    settings = settings or default_settings
    carrier = (carrier or "manual").lower()
    cls = _REAL.get(carrier, ManualAdapter)
    if settings.demo_mode and carrier not in ("manual",):
        return DemoAdapter(settings, carrier=carrier)
    return cls(settings)


def carrier_status(settings=None) -> list[dict]:
    """Configuration state of every carrier — powers the Settings screen."""
    settings = settings or default_settings
    out = []
    for name in CARRIERS:
        adapter = _REAL[name](settings)
        if settings.demo_mode and name != "manual":
            adapter = DemoAdapter(settings, carrier=name)
        out.append({
            "name": name,
            "label": CARRIER_LABELS[name],
            "abbr": CARRIER_ABBR[name],
            "configured": adapter.configured,
            "missing": adapter.missing_config() if hasattr(adapter, "missing_config") else [],
            "demo": settings.demo_mode and name != "manual",
        })
    return out


def tracking_url_for(carrier: str, tracking_number: str) -> str:
    tn = (tracking_number or "").strip()
    return {
        "dhl": f"https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={tn}",
        "fedex": f"https://www.fedex.com/fedextrack/?trknbr={tn}",
        "aramex": f"https://www.aramex.com/track/results?ShipmentNumber={tn}",
        "ups": f"https://www.ups.com/track?tracknum={tn}",
        "dhlecom": f"https://www.dhl.com/global-en/home/tracking/tracking-ecommerce.html?tracking-id={tn}",
        "colissimo": f"https://www.laposte.fr/outils/suivre-vos-envois?code={tn}",
        "track17": f"https://t.17track.net/en#nums={tn}",
    }.get((carrier or "").lower(), "")


# --------------------------------------------------------- auto-detection
def detect_carrier(tracking_number: str) -> list[str]:
    """Return carrier candidates ordered by confidence (best guess first)."""
    raw = (tracking_number or "").strip()
    clean = re.sub(r"[\s\-_]", "", raw).upper()
    if not clean:
        return []

    # UPS: 1Z + 16 characters
    if re.fullmatch(r"1Z[0-9A-Z]{16}", clean):
        return ["ups", "manual"]
    if re.fullmatch(r"T\d{10}", clean):
        return ["ups", "manual"]

    # FedEx: 12 / 15 digit, or the classic 3-8-8 dashed air waybill, or 96-prefixed
    if re.fullmatch(r"\d{3}-\d{8}", raw):
        return ["fedex"]
    if clean.isdigit() and len(clean) in (12, 15):
        return ["fedex", "aramex"]
    if clean.isdigit() and (len(clean) in (18, 20, 22) or clean.startswith("96")):
        return ["fedex", "ups"]

    # DHL eCommerce / Parcel: GM…, LX…DE, RX…DE style numbers
    if re.fullmatch(r"(GM|LX|RX|UV)\d{8,20}[A-Z]{0,2}", clean):
        return ["dhlecom", "dhl"]

    # DHL Express: 10-digit, plus JJD/JVGL/GM variants seen on express products
    if re.fullmatch(r"(JJD|JVGL|JD)\d{6,}", clean):
        return ["dhl"]
    if re.fullmatch(r"GM\d{16,18}", clean):
        return ["dhlecom", "dhl"]

    # Colissimo / La Poste: S10 numbers with FR suffix, or 6A/8R style barcodes
    if re.fullmatch(r"[A-Z]{2}\d{9}FR", clean):
        return ["colissimo", "manual"]
    if re.fullmatch(r"[68][A-Z]\d{8,12}", clean):
        return ["colissimo", "manual"]

    # S10 numbers from other postal operators -> 17TRACK (it resolves the operator for you)
    if re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", clean):
        return ["track17", "manual"]

    if clean.isdigit():
        n = len(clean)
        if n == 10:
            return ["dhl", "aramex"]
        if n in (8, 9, 11):
            return ["aramex", "dhl"]
        if n == 7:
            return ["aramex"]
        if n == 13:
            return ["colissimo", "aramex", "manual"]

    # anything else: manual entry, or hand it to the 17TRACK aggregator which
    # resolves 3,000+ couriers (EMS, China Post, national posts…)
    return ["manual", "track17"]


def guess_carrier(tracking_number: str) -> str:
    candidates = detect_carrier(tracking_number)
    return candidates[0] if candidates else "manual"
