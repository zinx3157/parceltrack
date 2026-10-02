#!/usr/bin/env bash
# ParcelDesk one-shot installer for Linux / macOS.
#   bash deploy/install.sh            install + create .env
#   bash deploy/install.sh --demo     install and start in demo mode
set -euo pipefail

cd "$(dirname "$0")/.."
DEMO_FLAG=""
[[ "${1:-}" == "--demo" ]] && DEMO_FLAG="--demo"

echo "==> Checking Python"
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"' \
  || { echo "Please install Python 3.10 or newer."; exit 1; }

echo "==> Creating virtual environment"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [[ ! -f .env ]]; then
  echo "==> Creating .env from template"
  cp .env.example .env
  SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
  if sed --version >/dev/null 2>&1; then
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
  else
    sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env   # macOS
  fi
  echo "    A random SECRET_KEY was generated."
  echo "    Edit .env to add your DHL / FedEx / Aramex / SMTP credentials."
fi

mkdir -p data

echo "==> Starting ParcelDesk${DEMO_FLAG:+ (demo mode)}"
echo "    Dashboard: http://localhost:8000   — press Ctrl+C to stop"
exec python run.py --host 0.0.0.0 --port 8000 ${DEMO_FLAG}
