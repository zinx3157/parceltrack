"""Colissimo (La Poste) adapter — Enterprise REST tracking.

Auth: header `X-Okapi-Key` (key issued with your Colissimo Enterprise contract).
Call: POST {base}/sls-ws/SlsServiceWSRest/2.0/track
Body: {"contractNumber": "...", "password": "...", "parcelNumber": "..."}

Colissimo's responses have varied between contract generations, so parsing walks the
JSON defensively for anything that looks like a dated tracking event (French wording is
normalised by the shared status mapper).
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt

_DATE_KEYS = ("date", "eventDate", "dateTime", "occurredAt", "timestamp")
_TEXT_KEYS = ("label", "message", "libelle", "eventLabel", "text", "description", "code")
_LOCATION_KEYS = ("localisation", "location", "lieu", "site", "city", "country")


class ColissimoAdapter(BaseAdapter):
    name = "colissimo"

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(timeout=settings.http_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.settings.colissimo_api_key and self.settings.colissimo_contract_number)

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.colissimo_api_key:
            missing.append("COLISSIMO_API_KEY")
        if not self.settings.colissimo_contract_number:
            missing.append("COLISSIMO_CONTRACT_NUMBER")
        return missing

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="Colissimo API credentials not configured")
        body = {
            "contractNumber": self.settings.colissimo_contract_number,
            "parcelNumber": tracking_number,
        }
        if self.settings.colissimo_password:
            body["password"] = self.settings.colissimo_password
        try:
            resp = self._client.post(
                f"{self.settings.colissimo_base_url}/sls-ws/SlsServiceWSRest/2.0/track",
                json=body,
                headers={"X-Okapi-Key": self.settings.colissimo_api_key,
                         "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"Colissimo connection error: {exc}")

        if resp.status_code in (401, 403):
            return TrackResult(ok=False, error="Colissimo: invalid API key (401/403)")
        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"Colissimo HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError:
            return TrackResult(ok=False, error="Colissimo: non-JSON response (check the v2 endpoint URL)")

        records = self._collect(data)
        events: list[TrackEvent] = []
        for rec in records:
            when = None
            for key in _DATE_KEYS:
                when = parse_dt(rec.get(key))
                if when:
                    break
            if not when:
                continue
            text = ""
            for key in _TEXT_KEYS:
                if rec.get(key):
                    text = str(rec[key])
                    break
            location = " ".join(str(rec[k]) for k in _LOCATION_KEYS if rec.get(k)).strip()
            events.append(TrackEvent(
                occurred_at=when,
                status=normalize_status(text, rec.get("code"), rec.get("eventCode")),
                status_text=text or "Update",
                location=location,
                description=str(rec.get("message") or rec.get("description") or ""),
                raw=rec,
            ))
        events.sort(key=lambda e: e.occurred_at)
        if not events:
            error = self._error_message(data) or "Colissimo: no tracking events for this parcel number"
            return TrackResult(ok=False, error=error, raw=data)
        return TrackResult(ok=True, events=events, raw=data)

    def _collect(self, data) -> list[dict]:
        found: list[dict] = []

        def looks_like_event(obj: dict) -> bool:
            return any(k in obj for k in _DATE_KEYS) and any(k in obj for k in _TEXT_KEYS)

        def walk(node):
            if isinstance(node, dict):
                if looks_like_event(node):
                    found.append(node)
                    return
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return found

    def _error_message(self, data) -> str:
        if isinstance(data, dict):
            for key in ("errorMessage", "message", "returnMessage", "error"):
                if isinstance(data.get(key), str) and data[key].strip():
                    return f"Colissimo: {data[key][:160]}"
        return ""
