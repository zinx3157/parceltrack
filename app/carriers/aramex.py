"""Aramex carrier adapter — Shipping API v2 (TrackShipments).

Auth: your Aramex account credentials (username, password, account number, PIN,
entity and country code) issued by Aramex for API access.
Endpoint: POST {base}/Tracking/Service_1_0.svc/json/TrackShipments

Aramex has shipped a few variants of this response over time, so parsing walks
the JSON defensively and picks up any record that looks like a tracking update.
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt

_DATE_KEYS = ("UpdateDateTime", "EventDate", "DateTime", "Date", "Timestamp", "UpdateDate")
_TEXT_KEYS = ("UpdateDescription", "Description", "Comments", "Activity", "Status", "Event")
_LOC_KEYS = ("UpdateLocation", "Location", "City", "Country", "Station", "Branch")


class AramexAdapter(BaseAdapter):
    name = "aramex"

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(timeout=settings.http_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.settings.aramex_username and self.settings.aramex_password
                    and self.settings.aramex_account_number)

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.aramex_username:
            missing.append("ARAMEX_USERNAME")
        if not self.settings.aramex_password:
            missing.append("ARAMEX_PASSWORD")
        if not self.settings.aramex_account_number:
            missing.append("ARAMEX_ACCOUNT_NUMBER")
        return missing

    def _client_info(self) -> dict:
        s = self.settings
        return {
            "UserName": s.aramex_username,
            "Password": s.aramex_password,
            "Version": "v1.0",
            "AccountNumber": s.aramex_account_number,
            "AccountPin": s.aramex_account_pin,
            "AccountEntity": s.aramex_account_entity,
            "AccountCountryCode": s.aramex_account_country_code,
        }

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="Aramex API credentials not configured")
        url = f"{self.settings.aramex_base_url}/Tracking/Service_1_0.svc/json/TrackShipments"
        body = {
            "ClientInfo": self._client_info(),
            "Shipments": [tracking_number],
            "GetLastTrackingUpdateOnly": False,
        }
        try:
            resp = self._client.post(url, json=body,
                                     headers={"Accept": "application/json",
                                              "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"Aramex connection error: {exc}")

        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"Aramex HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError:
            return TrackResult(ok=False, error="Aramex: non-JSON response (check endpoint/v2 URL)")

        if data.get("HasErrors"):
            notifications = data.get("Notifications") or []
            msg = notifications[0].get("Message") if notifications else "unknown error"
            return TrackResult(ok=False, error=f"Aramex: {msg}", raw=data)

        records = self._collect_updates(data)
        events: list[TrackEvent] = []
        for rec in records:
            dt = None
            for key in _DATE_KEYS:
                dt = parse_dt(rec.get(key))
                if dt:
                    break
            if not dt:
                continue
            text = ""
            for key in _TEXT_KEYS:
                if rec.get(key):
                    text = str(rec[key])
                    break
            location = " ".join(str(rec.get(k)) for k in _LOC_KEYS if rec.get(k)).strip()
            events.append(
                TrackEvent(
                    occurred_at=dt,
                    status=normalize_status(text, rec.get("UpdateCode")),
                    status_text=text or "Update",
                    location=location,
                    description=str(rec.get("Comments") or rec.get("Details") or ""),
                    raw=rec,
                )
            )
        events.sort(key=lambda e: e.occurred_at)
        if not events:
            return TrackResult(ok=False, error="Aramex: no tracking updates found yet", raw=data)
        return TrackResult(ok=True, events=events, raw=data)

    # ------------------------------------------------------------- helpers
    def _collect_updates(self, data: dict) -> list[dict]:
        """Walk the response and collect every dict that carries a date + status."""
        found: list[dict] = []

        def looks_like_update(obj: dict) -> bool:
            has_date = any(k in obj for k in _DATE_KEYS)
            has_text = any(k in obj for k in _TEXT_KEYS)
            return has_date and has_text

        def walk(node):
            if isinstance(node, dict):
                if looks_like_update(node):
                    found.append(node)
                    return
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return found
