#!/usr/bin/env python3
"""ParcelDesk launcher.

    python run.py                 # normal mode (carrier APIs from your .env)
    python run.py --demo          # demo mode: simulated carrier data, no credentials needed
    python run.py --port 8080 --host 0.0.0.0
    python run.py --seed-demo     # add sample parcels to the current database and exit
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ParcelDesk parcel tracking platform")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                        help="bind address (use 0.0.0.0 to expose on your network)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--demo", action="store_true",
                        help="simulate carrier APIs (no credentials required)")
    parser.add_argument("--no-scheduler", action="store_true", help="disable background sync jobs")
    parser.add_argument("--seed-demo", action="store_true",
                        help="seed sample parcels into the database and exit")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = parser.parse_args()

    if args.demo:
        os.environ["DEMO_MODE"] = "true"

    if args.seed_demo:
        os.environ.setdefault("DEMO_MODE", "true")
        from app.database import Base, SessionLocal, engine
        from app.seed import ensure_admin, seed_demo_data

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            ensure_admin(db)
            result = seed_demo_data(db, force=False)
            print(f"Seed complete: {result}")
        finally:
            db.close()
        return 0

    if args.no_scheduler:
        os.environ["SYNC_ON_STARTUP"] = "false"

    import uvicorn

    if args.reload:
        os.environ["UVICORN_RELOAD"] = "1"
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True)
    else:
        from app.main import app
        uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
