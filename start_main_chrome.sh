#!/bin/bash
# Launch Chrome with remote debugging enabled on the ordinary-ticket target match.
# IMPORTANT: Close ALL Chrome windows before running this.

TARGET_URL="https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/table/1/lang/en"

echo "============================================================"
echo "  Starting Chrome with Remote Debugging (port 9222)"
echo "============================================================"
echo ""
echo "  1. Pass FIFA queue/captcha/login in this Chrome window"
echo "  2. Keep the target match tab open"
echo "  3. Then run: python3 main_ticket_monitor.py --once"
echo ""
echo "  Target: $TARGET_URL"
echo ""
echo "============================================================"
echo ""

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -f "$CHROME" ]; then
    echo "[ERROR] Chrome not found at: $CHROME"
    echo "  If Chrome is installed elsewhere, edit this script."
    exit 1
fi

"$CHROME" \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/.chrome-fifa-main-debug" \
    --no-first-run \
    --no-default-browser-check \
    "$TARGET_URL"
