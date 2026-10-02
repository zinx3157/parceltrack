"""DHL Express carrier adapter — 'Shipment Tracking - Unified' API.

Docs: https://developer.dhl.com  ->  Shipment Tracking - Unified
Auth: HTTP Basic, username = API Key, password = API Secret.
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt


class DHLAdapter(BaseAdapter):
    name = "dhl"

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={"Accept": "application/json"},
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.dhl_api_key and self.settings.dhl_api_secret)

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.dhl_api_key:
            missing.append("DHL_API_KEY")
        if not self.settings.dhl_api_secret:
            missing.append("DHL_API_SECRET")
        return missing

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="DHL API credentials not configured")
        url = f"{self.settings.dhl_url}/shipments/{tracking_number}/tracking"
        params = {"language": "en", "limit": 100, "offset": 0}
        auth = (self.settings.dhl_api_key, self.settings.dhl_api_secret)
        try:
            resp = self._client.get(url, params=params, auth=auth)
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"DHL connection error: {exc}")

        if resp.status_code == 404:
            return TrackResult(ok=False, error="DHL: tracking number not found yet")
        if resp.status_code in (401, 403):
            return TrackResult(ok=False, error="DHL: invalid API key/secret (401/403)")
        if resp.status_code == 429:
            return TrackResult(ok=False, error="DHL: rate limit reached, will retry later")
        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"DHL HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        shipments = data.get("shipments") or []
        if not shipments:
            return TrackResult(ok=False, error="DHL: no shipment data returned", raw=data)

        shipment = shipments[0]
        events: list[TrackEvent] = []
        for ev in shipment.get("events", []) or []:
            local = (ev.get("location") or {}).get("address") or {}
            location = ", ".join(
                [x for x in [local.get("addressLocality"), local.get("countryCode")] if x]
            )
            text = ev.get("status") or ev.get("description") or ""
            events.append(
                TrackEvent(
                    occurred_at=parse_dt(ev.get("timestamp") or ev.get("date")) or parse_dt(""),
                    status=normalize_status(text, ev.get("description"), code=ev.get("statusCode")),
                    status_text=text or "Update",
                    location=location,
                    description=ev.get("description") or "",
                    raw=ev,
                )
            )
        events = [e for e in events if e.occurred_at]

        eta = parse_dt(shipment.get("estimatedDeliveryDate") or shipment.get("deliveryDate"))
        status = shipment.get("status") or {}
        if not events and status:
            text = status.get("status") or status.get("description") or ""
            loc = (status.get("location") or {}).get("address") or {}
            dt = parse_dt(status.get("timestamp"))
            if dt:
                events.append(
                    TrackEvent(
                        occurred_at=dt,
                        status=normalize_status(text, status.get("description"),
                                                code=status.get("statusCode")),
                        status_text=text or "Current status",
                        location=", ".join([x for x in [loc.get("addressLocality"),
                                                        loc.get("countryCode")] if x]),
                        raw=status,
                    )
                )
        return TrackResult(ok=True, events=events, eta=eta, raw=data)
