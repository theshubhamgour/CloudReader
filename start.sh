#!/usr/bin/env bash
# Start CloudReader on this computer.
#   ./start.sh          normal start (recommended)
#   ./start.sh --phone  also open it from a phone/tablet on the same Wi-Fi
#   ./start.sh --dev    hot-reloading development servers
# Opens http://127.0.0.1:3000 in your browser. Press Ctrl+C to stop.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
MODE=""
HOST=127.0.0.1
for arg in "$@"; do
  case "$arg" in
    --dev) MODE="--dev" ;;
    --phone) HOST=0.0.0.0 ;;
    *) echo "Unknown option: $arg (use --phone or --dev)"; exit 1 ;;
  esac
done
BACKEND_PORT=8000
FRONTEND_PORT=3000

say()  { printf "  %s\n" "$*"; }
fail() { printf "\n  ✗ %s\n\n" "$*"; exit 1; }

echo ""
say "☁  CloudReader: getting ready…"
echo ""

# ---------------------------------------------------------------- prerequisites
missing=()
command -v ffmpeg >/dev/null 2>&1 || missing+=(ffmpeg)
command -v node   >/dev/null 2>&1 || missing+=(node)
PY="$(command -v python3.12 || command -v python3.13 || command -v python3.11 || true)"
if [ -z "$PY" ] && command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  PY="$(command -v python3)"
fi
[ -n "$PY" ] || missing+=(python@3.12)

if [ ${#missing[@]} -gt 0 ]; then
  say "These tools are needed but not installed: ${missing[*]}"
  if command -v brew >/dev/null 2>&1; then
    read -r -p "  Install them now with Homebrew? [Y/n] " ans
    if [[ "${ans:-Y}" =~ ^[Yy]?$ ]]; then
      brew install "${missing[@]}"
      PY="$(command -v python3.12 || command -v python3.13 || command -v python3.11 || true)"
    else
      fail "Install them with: brew install ${missing[*]}"
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    fail "Install them with: sudo apt-get install ffmpeg nodejs npm python3 python3-venv"
  else
    fail "Install Homebrew from https://brew.sh, then run: brew install ${missing[*]}"
  fi
fi
[ -n "$PY" ] || fail "Python 3.11 or newer is required. Install it with: brew install python@3.12"

# ---------------------------------------------------------------- ports
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
cloudreader_up() {
  curl -fs "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1 && curl -fs "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1
}
local_only() { lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null | grep -q "127.0.0.1:$FRONTEND_PORT"; }
lan_ip() { ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true; }
open_browser() { [ "${CLOUDREADER_NO_OPEN:-}" = "1" ] || open "$1" 2>/dev/null || xdg-open "$1" 2>/dev/null || true; }
phone_hint() {
  local ip; ip="$(lan_ip)"
  if [ -n "$ip" ]; then
    say "📱 On your phone (same Wi-Fi), open:  http://$ip:$FRONTEND_PORT"
  else
    say "📱 Couldn't detect this computer's Wi-Fi address. Find it in System Settings → Wi-Fi."
  fi
  say "  (Anyone on this Wi-Fi network can open it. Use --phone only on a network you trust.)"
}
stop_running() {
  lsof -t -iTCP:"$BACKEND_PORT" -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  for _ in $(seq 1 20); do
    port_busy "$BACKEND_PORT" || port_busy "$FRONTEND_PORT" || return 0
    sleep 0.5
  done
  fail "Couldn't stop the running CloudReader. Close its Terminal window (or press Ctrl+C there) and try again."
}

if port_busy "$BACKEND_PORT" || port_busy "$FRONTEND_PORT"; then
  if ! cloudreader_up; then
    for p in $BACKEND_PORT $FRONTEND_PORT; do
      port_busy "$p" && fail "Port $p is already in use by another program. Close it (see: lsof -i :$p) and try again."
    done
  fi
  if [ "$HOST" = "0.0.0.0" ] && local_only; then
    say "CloudReader is already running, but only for this computer (phones can't reach it)."
    read -r -p "  Restart it with phone access? [Y/n] " ans || ans=Y
    [[ "${ans:-Y}" =~ ^[Yy]?$ ]] || exit 0
    say "→ Stopping the running copy…"
    stop_running
  else
    say "CloudReader is already running → http://127.0.0.1:$FRONTEND_PORT"
    local_only || phone_hint
    open_browser "http://127.0.0.1:$FRONTEND_PORT"
    exit 0
  fi
fi

# ---------------------------------------------------------------- backend setup
cd "$ROOT/backend"
if [ ! -x .venv/bin/python ]; then
  say "→ First run: creating the Python environment…"
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.deps-ok ] || [ requirements.txt -nt .venv/.deps-ok ] || [ requirements-dev.txt -nt .venv/.deps-ok ]; then
  say "→ Installing backend packages (one time, ~1 minute)…"
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements-dev.txt
  touch .venv/.deps-ok
fi

# ---------------------------------------------------------------- frontend setup
cd "$ROOT/frontend"
if [ ! -d node_modules ] || [ package.json -nt node_modules/.package-lock.json ]; then
  say "→ Installing web app packages (one time, ~1 minute)…"
  npm install --no-fund --no-audit --loglevel=error
fi
if [ "$MODE" != "--dev" ] && { [ ! -f .next/BUILD_ID ] || [ -n "$(find app components lib next.config.ts -newer .next/BUILD_ID -print -quit 2>/dev/null)" ]; }; then
  say "→ Building the web app (only after updates, ~30 seconds)…"
  BUILD_LOG="$ROOT/data/logs/web-build.log"
  mkdir -p "$(dirname "$BUILD_LOG")"
  # Another build (e.g. a second ./start.sh) must finish first: Next.js allows one at a time.
  for i in $(seq 1 180); do
    pgrep -f "next build" >/dev/null 2>&1 || break
    [ "$i" = 1 ] && say "  Waiting for another build to finish…"
    sleep 1
  done
  # Next.js sometimes stops the first attempt with a one-off notice, so try twice.
  if ! npm run build >"$BUILD_LOG" 2>&1 && ! npm run build >"$BUILD_LOG" 2>&1; then
    echo ""; tail -n 15 "$BUILD_LOG" | sed 's/^/    /'
    fail "The web app failed to build. Full log: data/logs/web-build.log"
  fi
fi

# ---------------------------------------------------------------- run
cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cd "$ROOT/backend"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT --log-level warning &

cd "$ROOT/frontend"
if [ "$MODE" = "--dev" ]; then
  npx next dev -H $HOST -p $FRONTEND_PORT &
else
  npx next start -H $HOST -p $FRONTEND_PORT &
fi

ready=0
for _ in $(seq 1 120); do
  if curl -fs "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1 && curl -fs "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 0.5
done
[ $ready = 1 ] || fail "CloudReader didn't start. See data/logs/cloudreader.log for details."

echo ""
say "✓ CloudReader is running →  http://127.0.0.1:$FRONTEND_PORT"
if [ "$HOST" = "0.0.0.0" ]; then phone_hint; fi
say "  Keep this window open while you use it. Press Ctrl+C to stop."
echo ""
open_browser "http://127.0.0.1:$FRONTEND_PORT"
wait
