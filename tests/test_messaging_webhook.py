#!/usr/bin/env python3
"""End-to-end test of the WhatsApp/SMS alert pipeline.

Starts a tiny local HTTP server that stands in for a messaging gateway
(Africa's Talking, Vonage, Twilio proxy, n8n…), points ParcelDesk at it via
MESSAGING_PROVIDER=webhook, then:

  1. sends a test message through the API
  2. creates a parcel and pushes it to "delivered"
  3. checks the gateway actually received both messages
  4. checks the alerts were logged in the app with the right channel

Run it from the project root:   python tests/test_messaging_webhook.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # project root on sys.path

PORT = 9099
RECEIVED: list[dict] = []


class Gateway(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            RECEIVED.append(json.loads(self.rfile.read(length) or b"{}"))
        except json.JSONDecodeError:
            RECEIVED.append({"raw": "unparseable"})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # silence the default access log
        pass


def main() -> int:
    server = HTTPServer(("127.0.0.1", PORT), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # configure messaging BEFORE importing the app
    os.environ.update({
        "MESSAGING_ENABLED": "true",
        "MESSAGING_PROVIDER": "webhook",
        "WEBHOOK_URL": f"http://127.0.0.1:{PORT}/send",
        "WEBHOOK_TOKEN": "test-token",
        "MESSAGING_RECIPIENTS": "+261340000000,+261330000000",
        "DEMO_MODE": "true",
        "SYNC_ON_STARTUP": "false",
        "DATABASE_URL": "sqlite:///./data/messaging_test.db",
    })

    from fastapi.testclient import TestClient  # noqa: PLC0415
    from app.config import get_settings  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    get_settings.cache_clear()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = ""):
        print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    with TestClient(app) as client:
        login = client.post("/api/auth/login",
                            json={"email": "admin@example.com", "password": "admin123"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        status = client.get("/api/messaging", headers=headers).json()
        check("messaging provider detected", status["provider"] == "webhook" and status["configured"],
              f"{status['provider_label']}")

        # 1. explicit test message
        test = client.post("/api/messaging/test", headers=headers,
                           json={"to": "+261340000000"})
        check("test message sent", test.status_code == 200 and test.json().get("ok"),
              str(test.json())[:120])

        # 2. a real status change should trigger an alert automatically
        created = client.post("/api/parcels", headers=headers, json={
            "tracking_number": "MSGTEST-0001", "carrier": "dhl", "client_name": "Webhook Test Client",
            "sync_now": False}).json()
        parcel_id = created["id"]
        client.post(f"/api/parcels/{parcel_id}/events", headers=headers, json={
            "status": "delivered", "status_text": "Delivered - signed for by TEST"})

        # also exercise the stuck-parcel text path
        client.post("/api/notifications/stuck", headers=headers)

        # 3. did the gateway receive them?
        check("gateway received messages", len(RECEIVED) >= 2, f"{len(RECEIVED)} message(s)")
        if RECEIVED:
            sample = RECEIVED[-1]
            check("payload shape", "to" in sample and "message" in sample,
                  json.dumps(sample)[:140])
            delivered_alert = [m for m in RECEIVED if "delivered" in m.get("message", "").lower()]
            check("delivered alert delivered to both numbers", len(delivered_alert) >= 2,
                  f"{len(delivered_alert)} message(s)")

        # 4. logged in-app with the right channel?
        log = client.get("/api/notifications?limit=20", headers=headers).json()
        webhook_entries = [n for n in log if n["channel"] == "webhook" and n["ok"]]
        check("alerts logged as webhook channel", bool(webhook_entries),
              f"{len(webhook_entries)} ok entr(y/ies)")

        # cleanup
        client.delete(f"/api/parcels/{parcel_id}", headers=headers)

    server.shutdown()
    try:
        os.remove("./data/messaging_test.db")
    except OSError:
        pass

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("WhatsApp/SMS pipeline verified end to end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
