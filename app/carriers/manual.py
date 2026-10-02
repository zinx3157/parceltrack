"""Manual carrier — parcels tracked by hand (agent calls, WhatsApp, carrier website)."""
from __future__ import annotations

from .base import BaseAdapter, TrackResult


class ManualAdapter(BaseAdapter):
    name = "manual"

    @property
    def configured(self) -> bool:
        return True

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        return TrackResult(ok=False, error="Manual tracking — no carrier API polling")
