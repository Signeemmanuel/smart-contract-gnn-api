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
#   FULL=1              Install the heavy serving stack (requirements.txt)
#                       instead of the light test/stub set. Needs a GitHub
#                       credential for the private scgnn repo and several GB of
#                       disk. Only needed once the real analyze_source path is
#                       wired; the current stub runs fine on the light set.
#   SCGNN_SRC=<spec>    Where pip gets the scgnn package from. Default tracks the
#                       master branch over HTTPS. Override with a LOCAL CLONE to
#                       avoid re-auth/clone (handy on gpu-01), e.g.:
#                           SCGNN_SRC="$HOME/smart-contract-gnn-model" ./run.sh
#   HOST=0.0.0.0        Server bind host (default 0.0.0.0).
#   PORT=8000           Server bind port (default 8000).
#   PYTHON=python3      Interpreter used to build the venv.
#
set -euo pipefail

# Always operate from the repo root (this script's own directory).
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
FULL="${FULL:-0}"
SCGNN_SRC="${SCGNN_SRC:-git+https://github.com/Signeemmanuel/smart-contract-gnn-model.git@master}"

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
    log "Installing FULL serving stack (requirements.txt) - heavy; needs GitHub creds + disk"
    pip install -r requirements.txt
  else
    log "Installing light test/stub stack (no torch, no Slither, no Hub needed)"
    pip install --quiet -r requirements-dev.txt "uvicorn[standard]>=0.30,<1"
    if python -c "import scgnn.schema" >/dev/null 2>&1; then
      echo "scgnn already importable - skipping its install"
    else
      log "Installing scgnn (schema only, --no-deps) from: $SCGNN_SRC"
      if ! pip install --no-deps "$SCGNN_SRC"; then
        echo
        echo "Could not install scgnn from '$SCGNN_SRC'."
        echo "If the private repo is not credentialed here, point SCGNN_SRC at a"
        echo "local clone instead, e.g.:"
        echo "    SCGNN_SRC=\"\$HOME/smart-contract-gnn-model\" ./run.sh $ACTION"
        exit 1
      fi
    fi
  fi
}

run_tests() {
  log "Running tests"
  python -m pytest -q
}

serve() {
  if [ ! -f .env ] && [ -z "${HF_TOKEN:-}" ]; then
    echo "Note: no .env and no HF_TOKEN set - revision resolution will fail and"
    echo "/health will report model_loaded=false. That is expected at the stub"
    echo "stage (analysis is mocked); set HF_TOKEN in .env for the real bundle."
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