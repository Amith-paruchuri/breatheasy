#!/usr/bin/env bash
# One-command start for macOS / Linux:  ./start.sh
# First run installs everything (a few minutes). Then open http://localhost:5173
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ is required: https://nodejs.org/"; exit 1; }

echo "== Backend =="
cd backend
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Created backend/.env (PROVIDER=open: real data, no key needed)"; }
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT INT TERM
for _ in $(seq 1 30); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "The backend failed to start. See the error above (often a typo in backend/.env)."; exit 1
  fi
  python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1)" 2>/dev/null && break
  sleep 1
done
cd ..

echo "== Frontend =="
cd frontend
[ -d node_modules ] || npm install --no-audit --no-fund
echo
echo "Breatheasy is starting at http://localhost:5173  (Ctrl+C to stop)"
echo "On your phone (same Wi-Fi): http://$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') || echo YOUR-COMPUTER-IP):5173"
echo
npx vite --port 5173
