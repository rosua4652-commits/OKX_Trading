#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=== OKX Auto Trader ==="

# Python venv
if [ ! -d backend/.venv ]; then
  echo "Creating Python venv..."
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt

# Frontend build
if [ ! -d frontend/dist ]; then
  echo "Building frontend..."
  cd frontend && npm install --silent && npm run build && cd ..
fi

PORT="${OAT_PORT:-8080}"

echo "Starting server on http://127.0.0.1:${PORT}"
cd backend
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
