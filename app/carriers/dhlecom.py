"""DHL eCommerce / DHL Parcel adapter — DHL "Shipment Tracking - Unified" API.

Uses the same developer.dhl.com account as the DHL Express adapter, but the public
tracking host (api-eu.dhl.com) and the `DHL-API-Key` header:

    GET {base}/track/shipments?trackingNumber=RX123456789DE

Create the app at developer.dhl.com and subscribe to "Shipment Tracking - Unified".
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt


class DHLeCommerceAdapter(BaseAdapter):
    name = "dhlecom"

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(timeout=settings.http_timeout_seconds)

    @property
    def configured(self) -> bool:
        # falls back to the DHL Express key so one credential can serve both adapters
        return bool(self.settings.dhl_ecom_api_key or self.settings.dhl_api_key)

    def missing_config(self) -> list[str]:
        if not self.configured:
            return ["DHL_ECOM_API_KEY (or DHL_API_KEY)"]
        return []

    @property
    def _key(self) -> str:
        return self.settings.dhl_ecom_api_key or self.settings.dhl_api_key

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="DHL eCommerce API key not configured")
        try:
            resp = self._client.get(
                f"{self.settings.dhl_ecom_base_url}/track/shipments",
                params={"trackingNumber": tracking_number},
                headers={"DHL-API-Key": self._key, "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"DHL eCommerce connection error: {exc}")

        if resp.status_code == 404:
            return TrackResult(ok=False, error="DHL eCommerce: shipment not found")
        if resp.status_code in (401, 403):
            return TrackResult(ok=False, error="DHL eCommerce: invalid API key (401/403)")
        if resp.status_code == 429:
            return TrackResult(ok=False, error="DHL eCommerce: rate limit reached")
        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"DHL eCommerce HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        shipments = data.get("shipments") or []
        if not shipments:
            return TrackResult(ok=False, error="DHL eCommerce: no shipment data", raw=data)

        shipment = shipments[0]
        events: list[TrackEvent] = []
        for ev in shipment.get("events", []) or []:
            address = (ev.get("location") or {}).get("address") or {}
            text = ev.get("status") or ev.get("description") or ""
            events.append(TrackEvent(
                occurred_at=parse_dt(ev.get("timestamp")),
                status=normalize_status(text, ev.get("description"), code=ev.get("statusCode")),
                status_text=text or "Update",
                location=", ".join([x for x in [address.get("addressLocality"),
                                                address.get("countryCode")] if x]),
                description=ev.get("description") or "",
                raw=ev,
            ))
        events = [e for e in events if e.occurred_at]

        status = shipment.get("status") or {}
        if not events and status:
            address = (status.get("location") or {}).get("address") or {}
            when = parse_dt(status.get("timestamp"))
            if when:
                events.append(TrackEvent(
                    occurred_at=when,
                    status=normalize_status(status.get("status"), status.get("description"),
                                            code=status.get("statusCode")),
                    status_text=status.get("status") or status.get("description") or "Current status",
                    location=", ".join([x for x in [address.get("addressLocality"),
                                                    address.get("countryCode")] if x]),
                    raw=status,
                ))

        eta = (parse_dt(shipment.get("estimatedTimeOfDelivery"))
               or parse_dt(shipment.get("estimatedDeliveryDate")))
        return TrackResult(ok=True, events=events, eta=eta, raw=data)
