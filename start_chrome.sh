#!/bin/bash
# Launch Chrome with remote debugging enabled.
# IMPORTANT: Close ALL Chrome windows before running this.

echo "============================================================"
echo "  Starting Chrome with Remote Debugging (port 9222)"
echo "============================================================"
echo ""
echo "  1. Log in to FIFA in this Chrome window"
echo "  2. Navigate to the ticket page"
echo "  3. Then run: python fifa_monitor.py"
echo ""
echo "============================================================"
echo ""

# macOS Chrome path
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -f "$CHROME" ]; then
    echo "[ERROR] Chrome not found at: $CHROME"
    echo "  If Chrome is installed elsewhere, edit this script."
    exit 1
fi

# Launch Chrome with remote debugging
# Using a separate user data dir so it doesn't conflict with your normal Chrome
"$CHROME" \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/.chrome-fifa-debug" \
    --no-first-run \
    --no-default-browser-check \
    "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/date/product/10229225515651/contact-advantages/10229997072863,10230003371090/lang/es"
