#!/usr/bin/env bash
# One-command local setup for the EPC Project Intelligence Platform.
#
#   bash setup.sh              # set up, test, start the web UI and open it in the browser
#   bash setup.sh --no-serve   # set up and test only
#   bash setup.sh --no-open    # serve, but do not open a browser
#   bash setup.sh --demo       # set up, then run the CLI demo instead of the web UI
#   bash setup.sh --skip-tests
#   bash setup.sh --port 8080
#
# ponytail: the app itself is stdlib-only, so this creates a venv, installs pytest
# (the one dev dependency) and verifies the install by running the suite. No AWS
# account needed — every AWS binding stays inert without its env variable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
RUN_TESTS=1
SERVE=1
OPEN=1
DEMO=0
PORT=8000

while [ $# -gt 0 ]; do
  case "$1" in
    --no-serve) SERVE=0 ;;
    --no-open) OPEN=0 ;;
    --demo) DEMO=1; SERVE=0 ;;
    --skip-tests) RUN_TESTS=0 ;;
    --port) PORT="${2:?--port needs a value}"; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n==> %s\n' "$1"; }

# 1. Python 3.10+
say "Checking Python"
PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  command -v "$cand" >/dev/null 2>&1 || continue
  if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required but was not found." >&2
  echo "Install it from https://www.python.org/downloads/ or via: brew install python@3.12" >&2
  exit 1
fi
echo "    using $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# 2. Virtual environment
if [ -x "$VENV/bin/python" ]; then
  say "Reusing virtualenv at .venv"
else
  say "Creating virtualenv at .venv"
  "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

# 3. Dev dependency (pytest). The platform code itself is stdlib-only.
say "Installing dev dependencies (pytest)"
"$VPY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
if ! "$VPY" -m pip install --quiet pytest; then
  echo "    WARNING: could not install pytest (offline?). The demo and web UI still work." >&2
  RUN_TESTS=0
fi

# 4. Verify
if [ "$RUN_TESTS" -eq 1 ]; then
  say "Running test suite"
  "$VPY" -m pytest -q "$ROOT/tests"
else
  say "Skipping tests"
fi

cd "$ROOT"

if [ "$DEMO" -eq 1 ]; then
  say "Running CLI demo"
  exec "$VPY" demo.py
fi

if [ "$SERVE" -eq 0 ]; then
  cat <<BANNER

==> Setup complete.

  Activate the environment:   source .venv/bin/activate
  CLI demo (stdout only):     python3 demo.py
  Web UI:                     python3 serve.py   → http://localhost:$PORT
  Tests:                      python3 -m pytest -q tests

  AWS is optional: every binding is inert without its env variable
  (EPC_S3_BUCKET, EPC_AUDIT_TABLE, EPC_EVENT_BUS, EPC_LLM). To deploy: bash infra/deploy.sh

BANNER
  exit 0
fi

# 5. Serve. serve.py builds the whole pipeline before it starts listening, so we
# poll for the port instead of guessing how long that takes, then open a browser.
URL="http://localhost:$PORT"
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Stop that process or re-run with --port <n>." >&2
  exit 1
fi

say "Starting web UI (building pipeline, this takes a few seconds)"
EPC_PORT="$PORT" "$VPY" -u serve.py &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Server exited before it was ready — see the output above." >&2
    exit 1
  fi
  if "$VPY" - "$URL" <<'PY' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=2).read(1)
PY
  then ready=1; break; fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "Server did not become ready in 60s." >&2
  exit 1
fi

cat <<BANNER

==> Ready.

  Landing page:   $URL
  Dashboard:      $URL/app.html
  State API:      $URL/api/state

  Press Ctrl-C to stop.

BANNER

if [ "$OPEN" -eq 1 ]; then
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi

wait "$SERVER_PID"
