"""
FIFA World Cup 2026 Ticket Availability Monitor
Connects to your real Chrome browser via CDP (Chrome DevTools Protocol).
No fake browser = no bot detection.

Usage:
  1. Close ALL Chrome windows
  2. Run: ./start_chrome.sh
  3. In that Chrome, go to FIFA and log in normally
  4. Navigate to the ticket page with Argentina matches visible
  5. Run: python fifa_monitor.py
"""

import time
import random
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# =============================================================================
# CONFIGURATION
# =============================================================================

CHECK_INTERVAL = 60  # Base interval in seconds
CDP_URL = "http://localhost:9222"  # Chrome DevTools Protocol endpoint
STATE_FILE = "monitor_state.json"
AUTO_BUY_MATCHES = {"19", "43", "70"}
TEST_MODE_MATCHES = {"86"}
ATTEMPT_COOLDOWN_SECONDS = 90

# Main ticket page URL (official shop)
TICKET_URL = "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/date/product/10229225515651/contact-advantages/10229997072863,10230003371090/lang/es"

# Argentina matches to monitor
ARGENTINA_MATCHES = {
    "19": "Argentina vs Algeria - Tue 16 Jun - Kansas City Stadium",
    "43": "Argentina vs Austria - Mon 22 Jun - Dallas Stadium",
    "70": "Jordan vs Argentina - Sat 27 Jun - Dallas Stadium",
    "86": "Round of 32 (Argentina) - TBD",
}

# Direct URLs for matches we know
MATCH_URLS = {
    "19": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700907/contact-advantages/10229997072863/lang/es",
    "43": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700931/contact-advantages/10229997072863/lang/es",
    "70": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700960/contact-advantages/10229997072863/lang/es",
}


# =============================================================================
# SOUND ALERTS
# =============================================================================


def play_alarm():
    """Play a loud repeating alarm on macOS"""
    print("\n" + "!" * 60)
    print("!!! ENTRADAS DISPONIBLES - ENTRADAS DISPONIBLES !!!")
    print("!" * 60 + "\n")

    for _ in range(10):
        try:
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Funk.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
        except Exception:
            print("\a")
            time.sleep(0.3)


# =============================================================================
# TICKET CHECKING
# =============================================================================


def load_state():
    """Load persisted match state so restarts do not retrigger old alerts."""
    path = Path(STATE_FILE)
    if not path.exists():
        return {}

    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(results):
    """Persist current match availability state."""
    state = {
        match_id: {
            "available": info.get("available", False),
            "status": info.get("status", ""),
        }
        for match_id, info in results.items()
    }

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def launch_autobuy_worker(match_id, test_mode=False):
    """Launch a separate worker so the main monitor keeps running."""
    args = [sys.executable, "autobuy_worker.py", match_id]
    if test_mode:
        args.append("--test-mode")

    try:
        subprocess.Popen(args)
        mode = "test-mode" if test_mode else "live"
        print(f"[*] Started autobuy worker for match {match_id} ({mode})")
        return True
    except Exception as e:
        print(f"[ERROR] Could not start autobuy worker for match {match_id}: {e}")
        return False


def check_argentina_matches(page):
    """
    Check availability of monitored matches on the page.
    Looks for div#availability_M{id} and checks CSS classes + text.
    """
    results = {}

    for match_id, description in ARGENTINA_MATCHES.items():
        try:
            container_selector = f'div[id="availability_M{match_id}"]'
            container = page.locator(container_selector)

            if container.count() == 0:
                results[match_id] = {
                    "status": "NOT FOUND ON PAGE",
                    "available": False,
                    "description": description,
                }
                continue

            avail_div = container.locator(".availability_status").first
            classes = avail_div.get_attribute("class") or ""

            # Get status text
            text_span = container.locator(".text span[aria-hidden='true']")
            if text_span.count() > 0:
                status_text = text_span.first.inner_text().strip()
            else:
                status_text = avail_div.inner_text().strip()

            # Determine availability from CSS classes and text
            is_sold_out = "sold_out" in classes
            text_lower = status_text.lower()
            is_available = (
                "limited_availability" in classes
                or "limited" in classes.lower()
                or ("available" in text_lower and "not available" not in text_lower)
                or "add to cart" in text_lower
                or "select" in text_lower
            )

            if is_available and not is_sold_out:
                results[match_id] = {
                    "status": status_text or "AVAILABLE!",
                    "available": True,
                    "description": description,
                    "classes": classes,
                }
            elif is_sold_out:
                results[match_id] = {
                    "status": status_text or "Not available",
                    "available": False,
                    "description": description,
                    "classes": classes,
                }
            else:
                # Unknown state - if not explicitly sold out, flag it
                results[match_id] = {
                    "status": status_text or f"UNKNOWN ({classes})",
                    "available": "sold_out" not in classes,
                    "description": description,
                    "classes": classes,
                }

        except Exception as e:
            results[match_id] = {
                "status": f"ERROR: {e}",
                "available": False,
                "description": description,
            }

    return results


def check_page_health(page):
    """Check if page is healthy (not blocked, not login, etc.)"""
    try:
        content = page.content().lower()
        url = page.url.lower()

        if "access blocked" in content or "access is temporarily restricted" in content:
            return False, "BLOCKED"
        if "unusual activity" in content:
            return False, "BOT DETECTED"
        if "login" in url and "logout" not in content:
            return False, "LOGIN REQUIRED"
        if "match selection" in content or "group stage" in content:
            return True, "OK"
        return True, "LOADED"
    except Exception as e:
        return False, f"ERROR: {e}"


# =============================================================================
# MAIN
# =============================================================================


def monitor_tickets():
    print("=" * 60)
    print("  FIFA World Cup 2026 - Argentina Ticket Monitor")
    print("  (Connected to your real Chrome via CDP)")
    print("=" * 60)
    print()
    for mid, desc in sorted(ARGENTINA_MATCHES.items(), key=lambda x: int(x[0])):
        print(f"  Match {mid}: {desc}")
    print()
    print(f"  Check interval: ~{CHECK_INTERVAL}s")
    print(f"  CDP endpoint: {CDP_URL}")
    print("=" * 60)
    print()

    with sync_playwright() as p:
        # Connect to existing Chrome instance
        print("[*] Connecting to your Chrome browser...")
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print()
            print("[ERROR] Could not connect to Chrome!")
            print(f"  Reason: {e}")
            print()
            print("  Make sure you:")
            print("  1. Closed ALL Chrome windows first")
            print("  2. Ran: ./start_chrome.sh")
            print("  3. Logged into FIFA in that Chrome window")
            print()
            return

        # Get the existing pages
        contexts = browser.contexts
        if not contexts:
            print("[ERROR] No browser contexts found. Open a tab in Chrome first.")
            return

        print(f"[OK] Connected! Found {len(contexts)} context(s)")

        # Find the correct FIFA list page tab, not waiting-room or seat pages.
        page = None
        for ctx in contexts:
            for p_page in ctx.pages:
                url = p_page.url.lower()
                if (
                    "fwc26-shop-usd.tickets.fifa.com/secure/selection/event/date/product/"
                    in url
                ):
                    page = p_page
                    print(f"[OK] Found FIFA tab: {p_page.url[:80]}...")
                    break
            if page:
                break

        if not page:
            # Fallback: use the first non-waiting-room FIFA tab if present.
            for ctx in contexts:
                for p_page in ctx.pages:
                    url = p_page.url.lower()
                    if (
                        "tickets.fifa.com" in url
                        and "access.tickets.fifa.com" not in url
                        and "/secure/selection/event/seat/performance/" not in url
                    ):
                        page = p_page
                        print(f"[OK] Found fallback FIFA tab: {p_page.url[:80]}...")
                        break
                if page:
                    break

        if not page:
            # No suitable FIFA tab found, use first page and navigate
            page = contexts[0].pages[0] if contexts[0].pages else contexts[0].new_page()
            print(f"[INFO] No FIFA tab found. Navigating to ticket page...")
            page.goto(TICKET_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

        # If we landed on the wrong FIFA page type, force the general list page.
        current_url = page.url.lower()
        if "/secure/selection/event/date/product/" not in current_url:
            print("[INFO] Switching to general match list page...")
            page.goto(TICKET_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

        # Check page health
        ok, reason = check_page_health(page)
        if not ok:
            print(f"[WARN] Page issue: {reason}")
            if reason in ("BLOCKED", "BOT DETECTED"):
                print("[ERROR] Your Chrome is blocked. Try:")
                print("  - Wait 15-30 min for the ban to expire")
                print("  - Use incognito mode")
                print("  - Try a different network/VPN")
                return
            if reason == "LOGIN REQUIRED":
                print(
                    "[INFO] Please log in to FIFA in the Chrome window, then restart this script."
                )
                return

        # Initial check
        print()
        print("[*] Running initial check...")
        results = check_argentina_matches(page)
        print_results(results)

        persisted_state = load_state()
        if persisted_state:
            print(f"[*] Loaded previous state from {STATE_FILE}")
        else:
            print(f"[*] No previous state found. Creating {STATE_FILE}")
        save_state(results)

        # Monitoring loop
        consecutive_errors = 0
        check_count = 0
        prev_results = persisted_state or results
        last_attempt_times = {}

        print("[*] Starting continuous monitoring... (Ctrl+C to stop)")
        print()

        while True:
            try:
                check_count += 1
                timestamp = datetime.now().strftime("%H:%M:%S")

                # Reload the page
                try:
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(random.uniform(2, 4))
                except PlaywrightTimeout:
                    print(f"[{timestamp}] WARN: Reload timeout")
                    consecutive_errors += 1
                    time.sleep(CHECK_INTERVAL)
                    continue

                # Check health
                ok, health = check_page_health(page)
                if not ok:
                    print(f"[{timestamp}] WARN: {health}")
                    consecutive_errors += 1
                    if consecutive_errors > 5:
                        print("[WARN] Too many errors. Pausing 5 minutes...")
                        time.sleep(300)
                        consecutive_errors = 0
                    else:
                        time.sleep(CHECK_INTERVAL * 2)
                    continue

                # Check matches
                results = check_argentina_matches(page)
                consecutive_errors = 0

                # Detect changes
                any_available = False
                newly_available = []

                for match_id, info in results.items():
                    prev = prev_results.get(match_id, {})
                    if info["available"]:
                        any_available = True
                        if not prev.get("available", False):
                            newly_available.append(match_id)

                # Launch separate worker attempts for available matches.
                now_ts = time.time()
                for match_id, info in results.items():
                    if not info.get("available"):
                        continue

                    if (
                        match_id not in AUTO_BUY_MATCHES
                        and match_id not in TEST_MODE_MATCHES
                    ):
                        continue

                    last_attempt = last_attempt_times.get(match_id, 0)
                    if now_ts - last_attempt < ATTEMPT_COOLDOWN_SECONDS:
                        continue

                    test_mode = match_id in TEST_MODE_MATCHES
                    if launch_autobuy_worker(match_id, test_mode=test_mode):
                        last_attempt_times[match_id] = now_ts

                # Print status line
                parts = []
                for mid in sorted(ARGENTINA_MATCHES.keys(), key=int):
                    info = results.get(mid, {})
                    if info.get("available"):
                        parts.append(f"M{mid}:AVAILABLE!")
                    elif "ERROR" in info.get("status", ""):
                        parts.append(f"M{mid}:ERR")
                    elif info.get("status") == "NOT FOUND ON PAGE":
                        parts.append(f"M{mid}:N/F")
                    else:
                        parts.append(f"M{mid}:--")

                print(f"[{timestamp}] #{check_count} {' | '.join(parts)}")

                # Alert on newly available matches
                for mid in newly_available:
                    info = results[mid]
                    print()
                    print("!" * 60)
                    print(f"  MATCH {mid} AHORA DISPONIBLE!")
                    print(f"  {info['description']}")
                    print(f"  Status: {info['status']}")
                    if mid in MATCH_URLS:
                        print(f"  URL: {MATCH_URLS[mid]}")
                    print("!" * 60)
                    print()

                if newly_available:
                    play_alarm()
                    # Screenshot
                    try:
                        path = f"tickets_found_{int(time.time())}.png"
                        page.screenshot(path=path)
                        print(f"[OK] Screenshot: {path}")
                    except Exception:
                        pass
                    time.sleep(CHECK_INTERVAL * 2)
                else:
                    delay = CHECK_INTERVAL + random.uniform(-10, 10)
                    time.sleep(max(delay, 20))

                prev_results = results
                save_state(results)

            except KeyboardInterrupt:
                print()
                print("[*] Monitor stopped.")
                break
            except Exception as e:
                print(f"[ERROR] {e}")
                consecutive_errors += 1
                time.sleep(CHECK_INTERVAL)

        print("[*] Bye!")


def print_results(results):
    """Pretty print results"""
    print()
    print("-" * 60)
    for mid in sorted(results.keys(), key=int):
        info = results[mid]
        tag = ">> AVAILABLE <<" if info["available"] else "Not available"
        print(f"  Match {mid}: {tag}")
        print(f"    {info['description']}")
        print(f"    Raw: {info['status']}")
        if info.get("classes"):
            print(f"    CSS: {info['classes']}")
        if info["available"] and mid in MATCH_URLS:
            print(f"    GO: {MATCH_URLS[mid]}")
        print()
    print("-" * 60)


if __name__ == "__main__":
    monitor_tickets()
