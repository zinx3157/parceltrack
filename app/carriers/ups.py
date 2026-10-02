"""UPS carrier adapter — OAuth2 client credentials + Track API.

Docs: https://developer.ups.com  ->  Track API ("Get Single Track Response")
Auth: POST {base}/security/v1/oauth/token  (HTTP Basic: client_id / client_secret)
Track: GET {base}/api/track/v1/details/{inquiryNumber}
Token endpoint and API host are the same (wwwcie.ups.com for the test environment).
"""
from __future__ import annotations

import threading
import time
import uuid

import httpx

from .base import BaseAdapter, TrackEvent, TrackResult, normalize_status, parse_dt


class UPSAdapter(BaseAdapter):
    name = "ups"

    _token: str | None = None
    _token_expiry: float = 0.0
    _lock = threading.Lock()

    def __init__(self, settings):
        super().__init__(settings)
        self._client = httpx.Client(timeout=settings.http_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.settings.ups_client_id and self.settings.ups_client_secret)

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.ups_client_id:
            missing.append("UPS_CLIENT_ID")
        if not self.settings.ups_client_secret:
            missing.append("UPS_CLIENT_SECRET")
        return missing

    def _get_token(self) -> tuple[str | None, str]:
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token, ""
            try:
                resp = self._client.post(
                    f"{self.settings.ups_url}/security/v1/oauth/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self.settings.ups_client_id, self.settings.ups_client_secret),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                return None, f"UPS auth connection error: {exc}"
            if resp.status_code >= 400:
                return None, f"UPS auth failed ({resp.status_code}): {resp.text[:200]}"
            payload = resp.json()
            self._token = payload.get("access_token")
            self._token_expiry = time.time() + float(payload.get("expires_in", 3600))
            return self._token, ""

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        if not self.configured:
            return TrackResult(ok=False, error="UPS API credentials not configured")
        token, err = self._get_token()
        if not token:
            return TrackResult(ok=False, error=err)

        headers = {
            "Authorization": f"Bearer {token}",
            "transId": uuid.uuid4().hex[:20],
            "transactionSrc": "ParcelDesk",
        }
        try:
            resp = self._client.get(
                f"{self.settings.ups_url}/api/track/v1/details/{tracking_number}",
                params={"locale": "en_US", "returnSignature": "false"},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            return TrackResult(ok=False, error=f"UPS connection error: {exc}")

        if resp.status_code == 401:
            self._token = None
            return TrackResult(ok=False, error="UPS: token rejected, will retry")
        if resp.status_code == 404:
            return TrackResult(ok=False, error="UPS: tracking number not found")
        if resp.status_code == 429:
            return TrackResult(ok=False, error="UPS: rate limit reached, will retry later")
        if resp.status_code >= 400:
            return TrackResult(ok=False, error=f"UPS HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        try:
            package = data["trackResponse"]["shipment"][0]["package"][0]
        except (KeyError, IndexError, TypeError):
            return TrackResult(ok=False, error="UPS: unexpected response (no package data)", raw=data)

        events: list[TrackEvent] = []
        for activity in package.get("activity", []) or []:
            address = (activity.get("location") or {}).get("address") or {}
            status_obj = activity.get("status") or {}
            text = status_obj.get("description") or status_obj.get("type") or ""
            when = parse_dt(f"{activity.get('date', '')} {activity.get('time', '')}".strip())
            if not when:
                when = parse_dt(activity.get("date"))
            events.append(TrackEvent(
                occurred_at=when or parse_dt(""),
                status=normalize_status(text, status_obj.get("code"), code=status_obj.get("type")),
                status_text=text or "Update",
                location=", ".join([x for x in [address.get("city"), address.get("stateProvince"),
                                                address.get("countryCode")] if x]),
                description=status_obj.get("description") or "",
                raw=activity,
            ))
        events = [e for e in events if e.occurred_at]

        eta = None
        for item in package.get("deliveryDate", []) or []:
            eta = parse_dt(item.get("date"))
            if eta:
                break
        if eta is None:
            eta = parse_dt((package.get("deliveryTime") or {}).get("endTime"))

        if not events:
            current = package.get("currentStatus") or {}
            when = parse_dt(package.get("deliveryDate", [{}])[0].get("date")) if package.get("deliveryDate") else None
            if when:
                events.append(TrackEvent(
                    occurred_at=when,
                    status=normalize_status(current.get("description"), current.get("code"),
                                            code=current.get("type")),
                    status_text=current.get("description") or "Current status",
                    raw=current,
                ))
        return TrackResult(ok=True, events=events, eta=eta, raw=data)
