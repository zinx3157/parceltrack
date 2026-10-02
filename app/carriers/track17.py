"""17TRACK aggregator adapter.

One key covers EMS, China Post, most national postal operators and 3,000+ couriers —
useful for the shipments that have no direct carrier API (EMS, Aliexpress/China Post,
local posts). Get a key at https://api.17track.net (free tier available).

Flow: POST /register (idempotent, tells 17TRACK to start tracking the number) then
POST /gettrackinfo returns events.  Header: 17token.
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt

# 17TRACK event "stage" values -> our statuses
_STAGE_MAP = {
    "delivered": "delivered",
    "intransit": "in_transit",
    "pickup": "picked_up",
    "undelivered": "exception",
    "exception": "exception",
    "expired": "exception",
    "inforeceived": "registered",
    "notfound": "unknown",
}


class Track17Adapter(BaseAdapter):
    name = "track17"

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(timeout=settings.http_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.settings.track17_api_key)

    def missing_config(self) -> list[str]:
        return [] if self.configured else ["TRACK17_API_KEY"]

    @property
    def _headers(self) -> dict:
        return {"17token": self.settings.track17_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"}

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="17TRACK API key not configured")

        # 1. make sure 17TRACK is tracking this number (safe to repeat)
        payload = [{"number": tracking_number,
                    "carrier": getattr(parcel, "carrier_hint", "") or None}]
        payload[0] = {k: v for k, v in payload[0].items() if v}
        try:
            self._client.post(f"{self.settings.track17_base_url}/register",
                              json=payload, headers=self._headers)
        except httpx.HTTPError:
            pass  # registration failures shouldn't stop the query

        # 2. fetch the tracking info
        try:
            resp = self._client.post(f"{self.settings.track17_base_url}/gettrackinfo",
                                     json=[{"number": tracking_number}], headers=self._headers)
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"17TRACK connection error: {exc}")

        if resp.status_code == 401:
            return TrackResult(ok=False, error="17TRACK: invalid API key (401)")
        if resp.status_code == 429:
            return TrackResult(ok=False, error="17TRACK: quota reached, will retry later")
        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"17TRACK HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json() or {}
        if data.get("code") not in (0, None):
            message = (data.get("data") or {}).get("errors") or data.get("message") or data.get("code")
            return TrackResult(ok=False, error=f"17TRACK: {message}", raw=data)

        accepted = ((data.get("data") or {}).get("accepted") or [])
        if not accepted:
            rejected = ((data.get("data") or {}).get("rejected") or [])
            reason = rejected[0].get("error", {}).get("message") if rejected else "no data yet"
            return TrackResult(ok=False, error=f"17TRACK: {reason}", raw=data)

        item = accepted[0]
        info = item.get("track_info") or {}
        providers = ((info.get("tracking") or {}).get("providers")) or []
        events: list[TrackEvent] = []
        for provider in providers:
            for ev in provider.get("events", []) or []:
                stage = str(ev.get("stage") or "").strip().lower().replace(" ", "")
                when = parse_dt(ev.get("time_iso") or ev.get("time_utc") or ev.get("time"))
                if not when:
                    continue
                text = ev.get("description") or ev.get("sub_status") or ""
                status = _STAGE_MAP.get(stage) or normalize_status(text, stage)
                events.append(TrackEvent(
                    occurred_at=when,
                    status=status,
                    status_text=text or "Update",
                    location=str(ev.get("location") or ""),
                    description=text,
                    raw=ev,
                ))
            if events:
                break  # first provider with data wins
        events.sort(key=lambda e: e.occurred_at)

        eta = None
        latest_status = info.get("latest_status") or {}
        if latest_status.get("sub_status"):
            events.append(TrackEvent(
                occurred_at=parse_dt(info.get("latest_event") or info.get("time_iso")) or None,
                status=normalize_status(str(latest_status.get("sub_status")),
                                        str(latest_status.get("status"))),
                status_text=str(latest_status.get("sub_status")),
                raw=latest_status,
            )) if parse_dt(info.get("latest_event") or info.get("time_iso")) else None

        if not events:
            return TrackResult(ok=False, error="17TRACK: no tracking events yet", raw=data)
        return TrackResult(ok=True, events=events, eta=eta, raw=data)
