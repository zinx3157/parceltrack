"""FedEx carrier adapter — OAuth2 + Track API v1.

Docs: https://developer.fedex.com  ->  Track API (get OAuth token + Track by tracking number)
Note: your FedEx developer account must be granted the *Track API* project before it works.
"""
from __future__ import annotations

import threading
import time

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt


class FedExAdapter(BaseAdapter):
    name = "fedex"

    _token: str | None = None
    _token_expiry: float = 0.0
    _lock = threading.Lock()

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(timeout=settings.http_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.settings.fedex_client_id and self.settings.fedex_client_secret)

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.fedex_client_id:
            missing.append("FEDEX_CLIENT_ID")
        if not self.settings.fedex_client_secret:
            missing.append("FEDEX_CLIENT_SECRET")
        return missing

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> tuple[str | None, str]:
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token, ""
            try:
                resp = self._client.post(
                    f"{self.settings.fedex_url}/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.fedex_client_id,
                        "client_secret": self.settings.fedex_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                return None, f"FedEx auth connection error: {exc}"
            if resp.status_code >= 400:
                return None, f"FedEx auth failed ({resp.status_code}): {resp.text[:200]}"
            payload = resp.json()
            self._token = payload.get("access_token")
            self._token_expiry = time.time() + float(payload.get("expires_in", 3600))
            return self._token, ""

    # ----------------------------------------------------------------- track
    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="FedEx API credentials not configured")
        token, err = self._get_token()
        if not token:
            return TrackResult(ok=False, error=err)

        body = {
            "includeDetailedScans": True,
            "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}],
        }
        try:
            resp = self._client.post(
                f"{self.settings.fedex_url}/track/v1/trackingnumbers",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-locale": "en_US",
                },
            )
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"FedEx connection error: {exc}")

        if resp.status_code == 401:
            self._token = None  # force refresh next run
            return TrackResult(ok=False, error="FedEx: token rejected, will retry")
        if resp.status_code == 429:
            return TrackResult(ok=False, error="FedEx: rate limit reached, will retry later")
        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"FedEx HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        output = (data.get("output") or {})
        complete = output.get("completeTrackResults") or []
        results = (complete[0].get("trackResults") if complete else None) or []
        if not results:
            alerts = output.get("alerts") or []
            msg = alerts[0].get("message") if alerts else "no results"
            return TrackResult(ok=False, error=f"FedEx: {msg}", raw=data)

        result = results[0]
        if result.get("error"):
            err_obj = result["error"]
            return TrackResult(ok=False,
                               error=f"FedEx: {err_obj.get('message') or err_obj.get('code')}",
                               raw=data)

        events: list[TrackEvent] = []
        for scan in result.get("scanEvents", []) or []:
            loc = scan.get("scanLocation") or {}
            text = scan.get("status") or scan.get("eventDescription") or ""
            events.append(
                TrackEvent(
                    occurred_at=parse_dt(scan.get("date")),
                    status=normalize_status(text, scan.get("eventDescription"),
                                            scan.get("derivedStatus"),
                                            code=scan.get("eventType") or scan.get("derivedStatus")),
                    status_text=text or "Update",
                    location=", ".join([x for x in [loc.get("city"),
                                                    loc.get("countryCode")] if x]),
                    description=scan.get("eventDescription") or "",
                    raw=scan,
                )
            )
        events = [e for e in events if e.occurred_at]

        latest = result.get("latestStatusDetail") or {}
        if not events and latest:
            dt = None
            for item in result.get("dateAndTimes", []) or []:
                if item.get("type") in ("ACTUAL_DELIVERY", "ESTIMATED_DELIVERY", "SHIP"):
                    dt = parse_dt(item.get("dateTime"))
                    break
            if dt:
                loc = latest.get("scanLocation") or {}
                events.append(
                    TrackEvent(
                        occurred_at=dt,
                        status=normalize_status(latest.get("statusByLocale"),
                                                latest.get("description"),
                                                code=latest.get("derivedCode") or latest.get("code")),
                        status_text=latest.get("statusByLocale") or latest.get("description") or "",
                        location=", ".join([x for x in [loc.get("city"),
                                                        loc.get("countryCode")] if x]),
                        raw=latest,
                    )
                )

        eta = None
        for item in result.get("dateAndTimes", []) or []:
            if item.get("type") in ("ESTIMATED_DELIVERY", "WINDOW_END"):
                eta = parse_dt(item.get("dateTime"))
                if eta:
                    break
        if eta is None:
            window = (result.get("estimatedDeliveryTimeWindow") or {}).get("window") or {}
            eta = parse_dt(window.get("ends"))
        return TrackResult(ok=True, events=events, eta=eta, raw=data)
