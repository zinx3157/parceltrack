#!/usr/bin/env bash
# Start ParcelDesk in demo mode (simulated carriers, no credentials needed).
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f .env ] || cp .env.example .env
echo "ParcelDesk (demo) -> http://localhost:${PORT:-8000}   login: admin@example.com / admin123"
exec .venv/bin/python run.py --demo --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
