#!/usr/bin/env bash
# One-shot local-dev bootstrap. Run from the repo root:
#   bash scripts/bootstrap.sh
#
# Installs Python 3.11 via brew if missing, creates a venv, installs backend deps,
# and installs frontend deps. Does NOT start the servers — that's two separate terminals.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Solace bootstrap"

# --- Python 3.11 -----------------------------------------------------------------
if ! command -v python3.11 >/dev/null 2>&1; then
  echo "  python3.11 not found."
  if command -v brew >/dev/null 2>&1; then
    echo "  installing via brew..."
    brew install python@3.11
  else
    echo "  ERROR: install Homebrew (https://brew.sh) or Python 3.11 manually, then re-run."
    exit 1
  fi
fi
echo "  python3.11 → $(python3.11 --version)"

# --- Backend venv ----------------------------------------------------------------
if [ ! -d backend/.venv ]; then
  echo "==> creating backend venv"
  python3.11 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install --upgrade pip wheel >/dev/null
echo "==> installing backend core deps"
pip install -r backend/requirements.txt
deactivate

# --- Frontend deps ---------------------------------------------------------------
if ! command -v npm >/dev/null 2>&1; then
  echo "  ERROR: npm not found. Install Node 20+ (https://nodejs.org) and re-run."
  exit 1
fi
echo "==> installing frontend deps"
(cd frontend && npm install --silent)

# --- .env sanity -----------------------------------------------------------------
if [ ! -f .env ]; then
  echo "==> .env not found; copying from .env.example"
  cp .env.example .env
  echo "  !! edit .env and add your API keys before starting the backend !!"
fi

cat <<EOF

==> Bootstrap complete.

Next: two terminals.

  Terminal 1 (backend):
    cd $REPO_ROOT/backend
    source .venv/bin/activate
    uvicorn main:app --reload --port 8000

  Terminal 2 (frontend):
    cd $REPO_ROOT/frontend
    npm run dev

Then open:
  Patient intake:      http://localhost:5173/demo
  Clinician dashboard: http://localhost:5173/demo/clinician  (PIN 123456)

To seed demo patients (after backend is running), in a third terminal:
    cd $REPO_ROOT/backend && source .venv/bin/activate
    python ../scripts/seed_demo.py

When the Triageist pickle files arrive, drop them in backend/models/ and also:
    pip install -r backend/requirements-ml.txt

EOF
