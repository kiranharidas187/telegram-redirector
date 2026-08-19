#!/usr/bin/env bash
# One-command setup & launch for the TG Reader portal: creates/reuses a venv,
# installs dependencies, makes sure .env exists, then starts app.py (which
# serves both the API and the frontend — there's nothing else to run).
set -e

cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Creating virtual environment (venv/)..."
  python3 -m venv venv
fi

echo "Installing dependencies..."
venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Created .env from .env.example — set API_ID and API_HASH in it first."
  echo "Get them from https://my.telegram.org/apps, then run ./run.sh again."
  exit 1
fi

URL="http://127.0.0.1:8765"
echo
echo "Starting the portal at $URL ..."

if command -v open >/dev/null 2>&1; then
  (sleep 1 && open "$URL" >/dev/null 2>&1 &)
elif command -v xdg-open >/dev/null 2>&1; then
  (sleep 1 && xdg-open "$URL" >/dev/null 2>&1 &)
fi

exec venv/bin/python3 app.py
