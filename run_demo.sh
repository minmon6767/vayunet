#!/usr/bin/env bash
# Sets up a virtualenv on first run, installs dependencies, and starts the
# backend. The frontend is served by Flask itself, so once this is running,
# open http://localhost:5050 in a browser -- there's nothing else to start.
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Setting up a virtual environment (first run only)..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo ""
echo "VayuNet is starting at http://localhost:${PORT:-5050}"
echo "Press Ctrl+C to stop."
echo ""

python3 backend/app.py
