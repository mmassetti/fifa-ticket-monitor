#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR="${PROFILE_DIR:-$HOME/.chrome-fifa-resale-debug}"
INTERVAL="${INTERVAL:-30}"
TARGET_URL="${TARGET_URL:-https://fwc26-resale-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/contact-advantages/10229997366844,10230133312745/lang/en}"

cd "$ROOT_DIR"

if [ -f ".env" ]; then
  echo "[*] Loading .env"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "============================================================"
echo "  FIFA 2026 resale-seat monitor"
echo "============================================================"
echo "Target: $TARGET_URL"
echo "Interval: ${INTERVAL}s"
echo ""

if ! curl -s "http://127.0.0.1:9222/json/version" >/dev/null 2>&1; then
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
    "$TARGET_URL" >/tmp/fifa-resale-chrome.log 2>&1 &

  echo "[*] Waiting for Chrome CDP on 127.0.0.1:9222..."
  for _ in $(seq 1 40); do
    if curl -s "http://127.0.0.1:9222/json/version" >/dev/null 2>&1; then
      echo "[OK] Chrome debug port is ready."
      break
    fi
    sleep 0.5
  done
else
  echo "[OK] Chrome debug port already active."
fi

echo ""
echo "[*] If FIFA shows queue/captcha/login, solve it in the Chrome window."
echo "[*] Open the seat map / let the page load seats; the monitor reads FIFA seatmap API calls."
echo ""
echo "[*] Starting monitor. Stop with Ctrl+C."
echo "============================================================"
echo ""

python3 resale_seat_monitor.py --interval "$INTERVAL"
