"""
Quick script to save FIFA session for reuse.
Run this once: it opens a browser, you log in, then press Enter to save the session.
"""

import json
import time
from playwright.sync_api import sync_playwright

# Official ticket shop URL (NOT resale)
TICKET_URL = "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/date/product/10229225515651/contact-advantages/10229997072863/lang/en"
SESSION_FILE = "fifa_session.json"

print("=" * 60)
print("  FIFA Session Saver")
print("=" * 60)
print("This will open a browser where you can log in to FIFA.")
print("After logging in, press Enter in this terminal to save the session.")
print("=" * 60)
print()

with sync_playwright() as p:
    print("[*] Opening browser...")
    browser = p.chromium.launch(headless=False)

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )

    # Anti-detection
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = { runtime: {} };
    """)

    page = context.new_page()

    print(f"[*] Navigating to: {TICKET_URL}")
    print("[*] Waiting for page to load...")
    print()

    page.goto(TICKET_URL, wait_until="networkidle", timeout=60000)
    time.sleep(5)

    # Try to dismiss cookie banner
    print("[*] Looking for cookie banner...")
    cookie_selectors = [
        'button:has-text("Accept")',
        'button:has-text("OK")',
        'button:has-text("I accept")',
        'button:has-text("Agree")',
        '[class*="cookie"] button',
        '[id*="cookie"] button',
    ]

    for selector in cookie_selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2000):
                print(f"  Found cookie button, clicking...")
                button.click()
                time.sleep(2)
                print("  [OK] Cookie banner dismissed")
                break
        except Exception:
            continue

    # Scroll to trigger lazy loading
    page.evaluate("window.scrollTo(0, 500)")
    time.sleep(1)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(2)

    print()
    print("=" * 60)
    print("  INSTRUCTIONS:")
    print("=" * 60)
    print("  1. Log in to your FIFA account in the browser window")
    print("  2. Complete any verification (email code, captcha, etc.)")
    print("  3. Make sure you can see the ticket page with matches")
    print("  4. Come back here and press ENTER to save the session")
    print("=" * 60)
    print()

    input("Press ENTER after you've logged in and see the ticket page... ")

    # Save session
    print()
    print("[*] Saving session...")
    try:
        storage = context.storage_state()
        with open(SESSION_FILE, "w") as f:
            json.dump(storage, f, indent=2)

        cookies_count = len(storage.get("cookies", []))
        print(f"[OK] Session saved to: {SESSION_FILE}")
        print(f"[OK] {cookies_count} cookies saved")
        print()
        print("You can now run: python fifa_monitor.py")
        print()

    except Exception as e:
        print(f"[ERROR] Could not save session: {e}")

    context.close()
    browser.close()

print("[*] Done!")
