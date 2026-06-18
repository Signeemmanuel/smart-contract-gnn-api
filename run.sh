#!/usr/bin/env bash
#
# run.sh - set up and run scgnn-api in one go.
#
# Usage:
#   ./run.sh            # setup + tests + start the dev server (default: 'all')
#   ./run.sh setup      # just create the venv and install dependencies
#   ./run.sh test       # setup + run the test suite
#   ./run.sh serve      # setup + start the server
#   ./run.sh all        # setup + tests + start the server
#
# Environment overrides:
#   FULL=1              Use the full serving stack (requirements.txt + the model
#                       stack you have installed, e.g. inside the Docker image).
#                       Locally, prefer the Dockerfile for the real stack.
#   HOST=0.0.0.0        Server bind host (default 0.0.0.0).
#   PORT=8000           Server bind port (default 8000).
#   PYTHON=python3      Interpreter used to build the venv.
#
# The scgnn inference package is VENDORED (a top-level scgnn/ directory). There is
# no install from GitHub; if scgnn is not importable, vendor it in and re-run.
#
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
FULL="${FULL:-0}"

ACTION="${1:-all}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

setup() {
  if [ ! -d "$VENV" ]; then
    log "Creating virtual environment ($VENV)"
    "$PYTHON" -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  python -m pip install --quiet --upgrade pip

  if [ "$FULL" = "1" ]; then
    log "Installing web layer (requirements.txt); the model stack must already be present"
    pip install -r requirements.txt
  else
    log "Installing light test/stub stack (no torch, no Slither, no Hub needed)"
    pip install --quiet -r requirements-dev.txt "uvicorn[standard]>=0.30,<1"
  fi

  if ! python -c "import scgnn.schema" >/dev/null 2>&1; then
    echo
    echo "Could not import scgnn.schema. The scgnn package must be VENDORED into"
    echo "this repo as a top-level scgnn/ directory (copied from the model repo at"
    echo "the trained-model commit). Add it and re-run."
    exit 1
  fi
}

run_tests() {
  log "Running tests"
  python -m pytest -q
}

serve() {
  # The light install has no torch/Slither, so serve the mock there unless the
  # full stack was installed (FULL=1) or the caller set SCGNN_MOCK explicitly.
  if [ "$FULL" != "1" ] && [ -z "${SCGNN_MOCK:-}" ]; then
    export SCGNN_MOCK=1
    echo "Light install -> serving in mock mode (SCGNN_MOCK=1)."
  fi
  if [ ! -f .env ] && [ -z "${HF_TOKEN:-}" ]; then
    echo "Note: no .env and no HF_TOKEN set - revision resolution will fail and"
    echo "/health will report model_loaded=false (expected for the mock)."
  fi
  log "Starting server on http://$HOST:$PORT  (Ctrl-C to stop)"
  exec uvicorn app.main:app --host "$HOST" --port "$PORT"
}

case "$ACTION" in
  setup) setup ;;
  test)  setup; run_tests ;;
  serve) setup; serve ;;
  all)   setup; run_tests; serve ;;
  *) echo "Unknown action: '$ACTION' (use: setup | test | serve | all)"; exit 2 ;;
esac