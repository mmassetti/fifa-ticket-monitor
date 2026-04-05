"""Capture FIFA internal network calls from your real Chrome session.

Usage examples:
  python inspect_api.py --match 86
  python inspect_api.py --match 19 --output api_match19.json

Expected setup:
  1. Chrome started with ./start_chrome.sh
  2. You are already past queue/login and can access the match page
"""

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"

MATCH_URLS = {
    "3": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700887/contact-advantages/10229997072863,10230003371090/lang/es",
    "19": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700907/contact-advantages/10229997072863/table/1/lang/es",
    "43": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700931/contact-advantages/10229997072863/lang/es",
    "70": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700960/contact-advantages/10229997072863/lang/es",
    "86": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725341/contact-advantages/10229997072863,10230003371090/table/1/lang/es",
}

INTERESTING_TOKENS = [
    "ajax/selection/event/submit",
    "selection/event/submit",
    "ajax/event/date/performances",
    "ajax/event/date/range",
    "quickbooking/updatedcart",
    "cart/shoppingcart",
    "cart",
    "seat",
    "ticket",
    "availability",
    "reserve",
    "stock",
    "quantity",
    "performance",
    "tnwr/v1",
]


def click_best_available(page):
    for selector in [
        "text=/Reserva el mejor sitio/i",
        "text=/Best available/i",
        "text=/Mejor sitio/i",
    ]:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible(timeout=1000):
                el.click()
                time.sleep(1.5)
                return True
        except Exception:
            continue
    return False


def set_quantity_one(page):
    try:
        page.evaluate(
            """
            () => {
                const selects = [...document.querySelectorAll('select')];
                const target = selects.find((node) => [...node.options].some((opt) => opt.value === '1' || opt.textContent.trim() === '1'));
                if (!target) return false;
                target.value = '1';
                target.dispatchEvent(new Event('input', { bubbles: true }));
                target.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            """
        )
        time.sleep(1)
        return True
    except Exception:
        return False


def click_add_to_cart(page):
    for selector in [
        "a#book",
        "#addToCartButtonContainer a",
        'a[role="button"]:has-text("Añadir al carrito")',
        'a[role="button"]:has-text("Anadir al carrito")',
        'button:has-text("Añadir al carrito")',
    ]:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible(timeout=1000):
                el.click(force=True)
                time.sleep(2)
                return True
        except Exception:
            continue
    return False


def is_interesting(response):
    req = response.request
    url = response.url.lower()
    content_type = response.headers.get("content-type", "").lower()
    return (
        req.resource_type in {"xhr", "fetch"}
        or "json" in content_type
        or any(token in url for token in INTERESTING_TOKENS)
    )


def capture_response(response):
    req = response.request
    try:
        body = response.text()[:4000]
    except Exception:
        body = "<unreadable>"

    return {
        "url": response.url,
        "status": response.status,
        "resource_type": req.resource_type,
        "content_type": response.headers.get("content-type", ""),
        "method": req.method,
        "post_data": req.post_data[:2000] if req.post_data else None,
        "body": body,
    }


def build_summary(captured):
    summary = []
    seen = set()
    for item in captured:
        key = (item["method"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        summary.append(
            {
                "method": item["method"],
                "status": item["status"],
                "url": item["url"],
                "content_type": item["content_type"],
            }
        )
    return summary


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--match", default="86", choices=sorted(MATCH_URLS.keys()))
    parser.add_argument("--output", default=None)
    parser.add_argument("--use-existing-tab", action="store_true")
    parser.add_argument("--list-tabs", action="store_true")
    parser.add_argument("--listen-only", action="store_true")
    parser.add_argument("--duration", type=int, default=20)
    return parser.parse_args()


def find_existing_match_page(browser, match_id):
    target = MATCH_URLS[match_id]
    performance_marker = target.split("/performance/")[1].split("/")[0]
    for context in browser.contexts:
        for page in context.pages:
            try:
                url = (page.url or "").lower()
            except Exception:
                url = ""
            title = ""
            try:
                title = page.title().lower()
            except Exception:
                pass

            if url and performance_marker in url:
                return context, page

            if (
                "/secure/selection/event/seat/performance/" in url
                and f"partido {match_id}" in title
            ):
                return context, page

            if match_id == "86" and "1j" in title and "2h" in title:
                return context, page
    return None, None


def main():
    args = parse_args()
    output = Path(args.output or f"api_inspection_match_{args.match}.json")
    summary_output = output.with_name(output.stem + "_summary.json")
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        if args.list_tabs:
            for i, context in enumerate(browser.contexts, start=1):
                print(f"Context {i}:")
                for j, page in enumerate(context.pages, start=1):
                    try:
                        title = page.title()
                    except Exception:
                        title = "<no title>"
                    print(f"  Tab {j}: {title} :: {page.url}")
            return

        if args.use_existing_tab:
            context, page = find_existing_match_page(browser, args.match)
            if not page:
                raise RuntimeError(
                    f"No existing tab found for match {args.match}. Open it manually first."
                )
        else:
            context = browser.contexts[0]
            page = context.new_page()

        def handle_response(response):
            try:
                if is_interesting(response):
                    captured.append(capture_response(response))
            except Exception:
                pass

        page.on("response", handle_response)

        if args.use_existing_tab:
            page.bring_to_front()
            time.sleep(1)
        else:
            page.goto(
                MATCH_URLS[args.match], wait_until="domcontentloaded", timeout=60000
            )
            time.sleep(3)

        if args.listen_only:
            print(
                f"Listening for network activity on match {args.match} for {args.duration}s..."
            )
            time.sleep(args.duration)
        else:
            click_best_available(page)
            set_quantity_one(page)
            click_add_to_cart(page)
            time.sleep(5)

        output.write_text(json.dumps(captured, indent=2))
        summary_output.write_text(json.dumps(build_summary(captured), indent=2))

        print(f"Captured {len(captured)} responses in {output}")
        print(f"Summary written to {summary_output}")


if __name__ == "__main__":
    main()
