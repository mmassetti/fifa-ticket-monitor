#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

TARGET_URL="https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725360/table/1/lang/en"
CDP_URL="http://127.0.0.1:9222/json/version"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR="$HOME/.chrome-fifa-main-debug"
INTERVAL="${INTERVAL:-30}"

if [ -f ".env" ]; then
  echo "[*] Loading .env"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "============================================================"
echo "  FIFA 2026 ordinary-ticket monitor"
echo "============================================================"
echo "Target: $TARGET_URL"
echo "Interval: ${INTERVAL}s"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 is required."
  exit 1
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import requests
PY
then
  echo "[ERROR] Python requests is not installed in this environment."
  echo "Run once:"
  echo "  python3 -m pip install -r requirements.txt"
  exit 1
fi

if curl -fsS "$CDP_URL" >/dev/null 2>&1; then
  echo "[OK] Chrome debug port already active."
else
  if [ ! -f "$CHROME" ]; then
    echo "[ERROR] Chrome not found at: $CHROME"
    exit 1
  fi

  echo "[*] Starting Chrome debug profile..."
  "$CHROME" \
    --remote-debugging-port=9222 \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    "$TARGET_URL" >/tmp/fifa-main-chrome.out 2>/tmp/fifa-main-chrome.err &

  echo "[*] Waiting for Chrome CDP on 127.0.0.1:9222..."
  for attempt in $(seq 1 60); do
    if curl -fsS "$CDP_URL" >/dev/null 2>&1; then
      echo "[OK] Chrome debug port is ready."
      break
    fi
    sleep 1
    if [ "$attempt" -eq 60 ]; then
      echo "[ERROR] Chrome debug port did not become ready."
      echo "Chrome stdout: /tmp/fifa-main-chrome.out"
      echo "Chrome stderr: /tmp/fifa-main-chrome.err"
      exit 1
    fi
  done
fi

echo ""
echo "[*] If FIFA shows queue/captcha/login, solve it in the Chrome window."
echo "[*] The monitor will reuse this same profile on future runs."
echo ""
echo "[*] Starting monitor. Stop with Ctrl+C."
echo "============================================================"
echo ""

exec python3 main_ticket_monitor.py --interval "$INTERVAL"
