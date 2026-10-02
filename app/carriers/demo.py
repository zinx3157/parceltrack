"""Demo / simulation adapter.

Used when DEMO_MODE=true so the whole platform (dashboard, alerts, reports,
timelines) can be tested end-to-end before the real carrier credentials are
plugged in. Timing is deterministic per tracking number, so results are stable
across runs.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

from .base import BaseAdapter, TrackEvent, TrackResult

ROUTES = [
    ("Paris (CDG), FR", "Dubai (DXB), AE"),
    ("Leipzig (LEJ), DE", "Istanbul (IST), TR"),
    ("Guangzhou (CAN), CN", "Dubai (DXB), AE"),
    ("Johannesburg (JNB), ZA", "Nairobi (NBO), KE"),
    ("London (LHR), GB", "Paris (CDG), FR"),
    ("Memphis (MEM), US", "Paris (CDG), FR"),
    ("Shanghai (PVG), CN", "Singapore (SIN), SG"),
    ("Lyon (LYS), FR", "Marseille (MRS), FR"),
]
DESTINATION = "Antananarivo (TNR), MG"

# Wording mirrors the real carriers so the timeline looks familiar.
WORDING = {
    "dhl": {
        "registered": "Shipment information received",
        "picked_up": "Shipment picked up",
        "hub": "Processed at {hub}",
        "customs": "Customs clearance status updated",
        "customs_done": "Customs clearance processing complete",
        "ofd": "Shipment is out for delivery",
        "delivered": "Delivered - Signed for by {signer}",
        "exception": "Delivery attempt made - recipient not available",
    },
    "fedex": {
        "registered": "Shipment information sent to FedEx",
        "picked_up": "Picked up",
        "hub": "In transit - Arrived at FedEx location {hub}",
        "customs": "Clearance in progress",
        "customs_done": "Clearance processing complete",
        "ofd": "On FedEx vehicle for delivery",
        "delivered": "Delivered - Left at front door, signed by {signer}",
        "exception": "Delivery exception - customer not available",
    },
    "ups": {
        "registered": "Label Created",
        "picked_up": "Pickup Scan",
        "hub": "Departed from Facility — {hub}",
        "customs": "Warehouse Scan — held for customs clearance",
        "customs_done": "Released by customs broker",
        "ofd": "Out For Delivery Today",
        "delivered": "Delivered — signed by {signer}",
        "exception": "Delivery Attempted — receiver unavailable",
    },
    "dhlecom": {
        "registered": "Shipment information received",
        "picked_up": "Shipment picked up by DHL eCommerce",
        "hub": "Arrived at DHL eCommerce facility {hub}",
        "customs": "Shipment is being cleared by customs",
        "customs_done": "Customs clearance completed",
        "ofd": "Shipment out for delivery",
        "delivered": "Shipment delivered — recipient {signer}",
        "exception": "Shipment delivery delayed",
    },
    "colissimo": {
        "registered": "Colis annoncé par l'expéditeur",
        "picked_up": "Pris en charge par La Poste",
        "hub": "Votre colis est en cours d'acheminement — {hub}",
        "customs": "Votre colis est en attente de dédouanement",
        "customs_done": "Colis dédouané — en cours d'acheminement",
        "ofd": "Votre colis est en cours de livraison",
        "delivered": "Colis livré au destinataire ({signer})",
        "exception": "Votre colis est en attente — destinataire absent",
    },
    "track17": {
        "registered": "Item pre-advised (electronic information received)",
        "picked_up": "Item picked up by carrier",
        "hub": "Item in transit — processed through {hub}",
        "customs": "Item held at customs for clearance",
        "customs_done": "Customs clearance completed",
        "ofd": "Item out for delivery",
        "delivered": "Item delivered, signed for by {signer}",
        "exception": "Delivery attempt unsuccessful",
    },
    "aramex": {
        "registered": "Shipment created in Aramex system",
        "picked_up": "Shipment picked up from shipper",
        "hub": "Shipment arrived at {hub} hub",
        "customs": "Shipment customs clearance in progress",
        "customs_done": "Shipment customs clearance completed",
        "ofd": "Shipment out for delivery with courier",
        "delivered": "Shipment delivered - received by {signer}",
        "exception": "Shipment delivery attempted - receiver unavailable",
    },
}
SIGNERS = ["RASOA", "RAKOTO", "ANDRIAN", "RANDRIA", "RAHARISOA", "BEMANANJARA"]


class DemoAdapter(BaseAdapter):
    """Simulates a carrier API response."""

    def __init__(self, settings, carrier: str = "dhl"):
        super().__init__(settings)
        self.name = carrier
        self.carrier = carrier
        self._wording = WORDING.get(carrier, WORDING["dhl"])

    @property
    def configured(self) -> bool:
        return True

    def track(self, tracking_number: str, parcel=None) -> TrackResult:
        seed = int(hashlib.sha1(tracking_number.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        created = getattr(parcel, "created_at", None) or (datetime.utcnow() - timedelta(days=3))
        origin, hub = rng.choice(ROUTES)
        transit_days = rng.choice([3, 4, 5, 6, 7, 8])
        signer = rng.choice(SIGNERS)

        # Simulated timeline: spread the journey over the last `transit_days`, so a
        # freshly added parcel shows history immediately instead of staying empty.
        created = min(created, datetime.utcnow() - timedelta(days=transit_days))

        # A realistic mix of journeys: some delivered, some moving, some stuck.
        rolled = rng.random()
        if rolled < 0.14:
            mode = "stuck_customs"
        elif rolled < 0.26:
            mode = "exception"
        elif rolled < 0.48:
            mode = "in_transit"
        elif rolled < 0.64:
            mode = "out_for_delivery"
        else:
            mode = "delivered"

        def at(fraction: float) -> datetime:
            return created + timedelta(days=transit_days * fraction)

        plan: list[tuple[float, str, str, str]] = [
            (0.02, "registered", self._wording["registered"], origin),
            (0.10, "picked_up", self._wording["picked_up"], origin),
            (0.28, "in_transit", self._wording["hub"].format(hub=hub), hub),
            (0.50, "in_transit", self._wording["hub"].format(hub=DESTINATION), DESTINATION),
            (0.62, "customs", self._wording["customs"], DESTINATION),
            (0.72, "customs", self._wording["customs_done"], DESTINATION),
            (0.85, "out_for_delivery", self._wording["ofd"], DESTINATION),
            (0.90, "exception", self._wording["exception"], DESTINATION),
            (1.00, "delivered", self._wording["delivered"].format(signer=signer), DESTINATION),
        ]
        # how far along each journey profile goes
        cut = {"in_transit": 4, "stuck_customs": 5, "out_for_delivery": 7,
               "exception": 8, "delivered": 9}[mode]
        if mode == "delivered":
            plan = plan[:7] + [plan[8]]  # skip the failed-attempt step

        now = datetime.utcnow()
        events = [
            TrackEvent(occurred_at=at(f), status=status,
                       status_text=text.format(signer=signer, hub=hub),
                       location=loc, description="", raw={"simulated": True})
            for f, status, text, loc in plan[:cut] if at(f) <= now
        ]
        events.sort(key=lambda e: e.occurred_at)
        eta = at(1.0)
        return TrackResult(ok=True, events=events, eta=eta if eta > now else None,
                           raw={"simulated": True, "profile": mode})
