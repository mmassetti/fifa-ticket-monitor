"""
Open a direct FIFA match tab and try to add 1 ticket using
"Reserva el mejor sitio" / "Best available".

This runs as a separate process so the main monitor can keep looping.
"""

import re
import sys
import time
import subprocess
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CDP_URL = "http://localhost:9222"
STATE_FILE = "autobuy_state.json"
CATEGORY_RETRY_COOLDOWN_SECONDS = 300

MATCH_URLS = {
    "19": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700907/contact-advantages/10229997072863/lang/es",
    "43": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700931/contact-advantages/10229997072863/lang/es",
    "70": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226700960/contact-advantages/10229997072863/lang/es",
    "86": "https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725341/contact-advantages/10229997072863,10230003371090/table/1/lang/es",
}


def log(message):
    ts = time.strftime("%H:%M:%S")
    print(f"[autobuy {ts}] {message}")


def play_cart_success_alarm():
    for _ in range(15):
        try:
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Glass.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.4)
        except Exception:
            print("\a")
            time.sleep(0.2)


def load_state():
    path = Path(STATE_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def category_key(match_id, category):
    return f"{match_id}:{category}"


def should_skip_category(state, match_id, category):
    entry = state.get(category_key(match_id, category), {})
    last_unavailable_at = entry.get("last_unavailable_at", 0)
    return (time.time() - last_unavailable_at) < CATEGORY_RETRY_COOLDOWN_SECONDS


def mark_category_unavailable(state, match_id, category):
    state[category_key(match_id, category)] = {
        "last_unavailable_at": time.time(),
        "result": "unavailable",
    }


def clear_category_state(state, match_id, category):
    state.pop(category_key(match_id, category), None)


def get_content_lower(page):
    try:
        return page.content().lower()
    except Exception:
        return ""


def click_best_available(page):
    selectors = [
        "text=/Reserva el mejor sitio/i",
        "text=/Best available/i",
        "text=/Best seat/i",
    ]
    for selector in selectors:
        try:
            tab = page.locator(selector).first
            if tab.count() > 0 and tab.is_visible(timeout=1000):
                tab.click()
                time.sleep(1.5)
                return True
        except Exception:
            continue
    return False


def extract_form_model(page):
    """Extract eventFormData metadata from the live DOM if available."""
    try:
        return page.evaluate(
            r"""
            () => {
                const normalize = (value) =>
                  (value || '')
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .toLowerCase();

                const parseIndex = (name) => {
                  const match = /eventFormData\[(\d+)\]\./.exec(name || '');
                  return match ? Number(match[1]) : null;
                };

                const model = {
                  performanceId: null,
                  csrfToken: null,
                  marketType: 'MAIN',
                  cachePage: 'true',
                  ballotId: null,
                  tourId: null,
                  categories: []
                };

                const perfInput = document.querySelector('[name="performanceId"]');
                if (perfInput) model.performanceId = perfInput.value;

                if (!model.performanceId) {
                  const match = /\/performance\/(\d+)/.exec(window.location.href);
                  if (match) model.performanceId = match[1];
                }

                const csrfInput = document.querySelector('[name="csrfToken"]');
                if (csrfInput) model.csrfToken = csrfInput.value;

                const marketInput = document.querySelector('[name="marketType"]');
                if (marketInput?.value) model.marketType = marketInput.value;

                const cacheInput = document.querySelector('[name="cachePage"]');
                if (cacheInput?.value) model.cachePage = cacheInput.value;

                const tourInput = document.querySelector('[name="tourId"]');
                if (tourInput) model.tourId = tourInput.value || null;

                const ballotInput = document.querySelector('[name="ballotId"]');
                if (ballotInput) model.ballotId = ballotInput.value || null;

                const byIndex = {};

                for (const input of document.querySelectorAll('[name^="eventFormData["]')) {
                  const index = parseIndex(input.name);
                  if (index === null) continue;
                  byIndex[index] = byIndex[index] || { index };

                  const key = input.name.split('.').pop();
                  byIndex[index][key] = input.value === '' ? null : input.value;

                  if (key === 'quantity') {
                    let row = input.closest('tr, li, .tariff, .table_container > div, .table_container > section, .table_container > article');
                    if (!row) row = input.parentElement;
                    const rowText = row ? normalize(row.innerText) : '';
                    const categoryMatch = /categoria\s+(\d+)|category\s+(\d+)/.exec(rowText);
                    byIndex[index].categoryNumber = categoryMatch ? Number(categoryMatch[1] || categoryMatch[2]) : null;
                    byIndex[index].rowText = rowText;
                  }
                }

                model.categories = Object.values(byIndex).sort((a, b) => a.index - b.index);
                return model;
            }
            """
        )
    except Exception as e:
        return {"error": str(e), "categories": []}


def acquire_csrf_via_page(page):
    try:
        return page.evaluate(
            r"""
            async () => {
                const response = await fetch('/ajax/selection/csrf/acquire', {
                  method: 'GET',
                  credentials: 'include',
                  headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                  }
                });
                const text = await response.text();
                return {
                  ok: response.ok,
                  status: response.status,
                  text
                };
            }
            """
        )
    except Exception as e:
        return {"ok": False, "status": 0, "text": str(e)}


def submit_via_page_api(page, payload):
    try:
        return page.evaluate(
            r"""
            async ({ payload }) => {
                const response = await fetch('/ajax/selection/event/submit?lang=es', {
                  method: 'POST',
                  credentials: 'include',
                  headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                  },
                  body: JSON.stringify(payload)
                });
                const text = await response.text();
                return {
                  ok: response.ok,
                  status: response.status,
                  text
                };
            }
            """,
            {"payload": payload},
        )
    except Exception as e:
        return {"ok": False, "status": 0, "text": str(e)}


def confirm_cart_via_navigation(page):
    try:
        page.goto(
            "https://fwc26-shop-usd.tickets.fifa.com/cart/shoppingCart",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(2)
        return page_shows_cart_success(page)
    except Exception:
        return False


def build_submit_payload(model, category_number, csrf_token):
    categories = []
    target_found = False

    for item in model.get("categories", []):
        category_number_for_item = item.get("categoryNumber")
        payload_item = {
            "advantageId": item.get("advantageId"),
            "priceLevelId": item.get("priceLevelId"),
            "seatCategory": item.get("seatCategory"),
            "audienceSubCategory": item.get("audienceSubCategory"),
        }

        if category_number_for_item == category_number:
            payload_item["quantity"] = "1"
            target_found = True

        categories.append(payload_item)

    if not target_found:
        return None

    return {
        "preferredAreas": {},
        "csrfToken": csrf_token,
        "eventFormData": categories,
        "tourId": model.get("tourId"),
        "ballotId": model.get("ballotId"),
        "cachePage": model.get("cachePage", "true"),
        "performanceId": model.get("performanceId"),
        "marketType": model.get("marketType", "MAIN"),
    }


def try_api_submit(page, match_id, category, test_mode=False):
    model = extract_form_model(page)
    if model.get("error"):
        return {"ok": False, "reason": f"form extract error: {model['error']}"}

    if not model.get("categories"):
        return {"ok": False, "reason": "no eventFormData categories found in DOM"}

    csrf = acquire_csrf_via_page(page)
    if not csrf.get("ok") or not csrf.get("text"):
        return {"ok": False, "reason": f"csrf acquire failed: {csrf.get('status')}"}

    payload = build_submit_payload(model, category, csrf.get("text"))
    if not payload:
        return {
            "ok": False,
            "reason": f"category {category} not mapped in eventFormData",
        }

    if test_mode:
        return {
            "ok": True,
            "reason": f"test-mode prepared API payload for category {category}",
            "payload": payload,
        }

    submit = submit_via_page_api(page, payload)
    if not submit.get("ok"):
        return {
            "ok": False,
            "reason": f"submit failed: {submit.get('status')} {submit.get('text', '')[:200]}",
        }

    if confirm_cart_via_navigation(page):
        return {"ok": True, "reason": "api submit reached shopping cart"}

    return {
        "ok": False,
        "reason": f"submit returned {submit.get('status')} but cart not confirmed: {submit.get('text', '')[:200]}",
    }


def select_category_quantity(page, category):
    """Best-effort selection of quantity=1 for a category row."""
    try:
        result = page.evaluate(
            """
            ({ category }) => {
                const normalize = (value) =>
                  (value || '')
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .toLowerCase();

                const wanted = [`categoria ${category}`, `category ${category}`];
                const nodes = [...document.querySelectorAll('div, li, tr')];

                const row = nodes.find((node) => {
                  const text = normalize(node.innerText);
                  return wanted.some((token) => text.includes(token));
                });

                if (!row) {
                  return { ok: false, reason: 'category row not found' };
                }

                let container = row;
                for (let i = 0; i < 4 && container; i += 1) {
                  const select = container.querySelector('select');
                  if (select) {
                    const hasOne = [...select.options].some((opt) => opt.value === '1' || opt.textContent.trim() === '1');
                    if (!hasOne) {
                      return { ok: false, reason: 'quantity 1 not present' };
                    }
                    select.value = '1';
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    return { ok: true, method: 'select' };
                  }
                  container = container.parentElement;
                }

                const button = [...row.querySelectorAll('button')].find((el) => {
                  const text = normalize(el.innerText);
                  return text.includes('anadir') || text.includes('añadir') || text.includes('add');
                });
                if (button) {
                  button.click();
                  return { ok: true, method: 'button' };
                }

                return { ok: false, reason: 'no selectable control found' };
            }
            """,
            {"category": category},
        )
        return result or {"ok": False, "reason": "no result"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def click_add_to_cart(page, test_mode=False):
    selectors = [
        "a#book",
        "#addToCartButtonContainer a",
        'a[role="button"]:has-text("Añadir al carrito")',
        'a[role="button"]:has-text("Anadir al carrito")',
        'a[role="button"]:has-text("Add to cart")',
        'button:has-text("Añadir al carrito")',
        'button:has-text("Add to cart")',
        'button:has-text("Anadir al carrito")',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.count() > 0 and button.is_visible(timeout=1000):
                button.click(force=True)
                time.sleep(2)
                if test_mode:
                    return {"ok": True, "reason": "test-mode clicked add-to-cart"}
                return {"ok": True, "reason": "clicked add-to-cart"}
        except Exception:
            continue

    try:
        clicked = page.evaluate(
            """
            () => {
                const anchor = document.querySelector('a#book')
                  || document.querySelector('#addToCartButtonContainer a')
                  || [...document.querySelectorAll('a[role="button"], button')].find((el) =>
                    /anadir al carrito|añadir al carrito|add to cart/i.test(el.innerText || '')
                  );
                if (!anchor) return false;
                anchor.click();
                return true;
            }
            """
        )
        if clicked:
            time.sleep(2)
            if test_mode:
                return {"ok": True, "reason": "test-mode clicked add-to-cart via js"}
            return {"ok": True, "reason": "clicked add-to-cart via js"}
    except Exception:
        pass

    return {"ok": False, "reason": "add-to-cart button not found"}


def page_shows_unavailable(page):
    content = get_content_lower(page)
    markers = [
        "actualmente no disponible",
        "not available currently",
        "no hay disponibilidad",
        "no availability",
        "selected ticket is not available",
        "boleto que has seleccionado no está disponible",
        "boleto que has seleccionado no esta disponible",
    ]
    return any(marker in content for marker in markers)


def page_shows_cart_success(page):
    content = get_content_lower(page)
    success_markers = [
        "tu carrito de compras",
        "your shopping cart",
        "checkout",
        "cart",
    ]
    empty_markers = [
        "carrito de compras está vacío",
        "carrito de compras esta vacio",
        "shopping cart is empty",
    ]
    return any(m in content for m in success_markers) and not any(
        m in content for m in empty_markers
    )


def attempt_match(page, match_id, test_mode=False):
    if match_id not in MATCH_URLS:
        log(f"No direct URL configured for match {match_id}")
        return False

    url = MATCH_URLS[match_id]
    log(f"Opening {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)

    clicked = click_best_available(page)
    if clicked:
        log("Opened 'Reserva el mejor sitio'")
    else:
        log("Best-available tab not found, continuing on current view")

    state = load_state()

    for category in [1, 2, 3]:
        if should_skip_category(state, match_id, category):
            log(f"Skipping category {category} due to recent unavailable result")
            continue

        log(f"Trying category {category} with quantity 1")
        api_result = try_api_submit(page, match_id, category, test_mode=test_mode)
        log(api_result.get("reason", "api attempt finished"))

        if api_result.get("ok") and test_mode:
            log(
                f"Test-mode API path available for match {match_id} category {category}"
            )
            return True

        if api_result.get("ok"):
            clear_category_state(state, match_id, category)
            save_state(state)
            log(
                f"Success: match {match_id} added to cart with category {category} via API"
            )
            play_cart_success_alarm()
            return True

        # Fallback to DOM interaction if API mapping/submit is unavailable.
        selected = select_category_quantity(page, category)
        if not selected.get("ok"):
            log(f"Category {category} not selectable: {selected.get('reason')}")
            mark_category_unavailable(state, match_id, category)
            save_state(state)
            continue

        time.sleep(1.5)
        add_result = click_add_to_cart(page, test_mode=test_mode)
        log(add_result.get("reason", "add attempt finished"))
        time.sleep(2)

        if page_shows_unavailable(page):
            log(f"Category {category} rejected as unavailable")
            mark_category_unavailable(state, match_id, category)
            save_state(state)
            continue

        if page_shows_cart_success(page):
            clear_category_state(state, match_id, category)
            save_state(state)
            if test_mode:
                log(
                    f"Test-mode detected cart success for match {match_id} category {category}"
                )
                play_cart_success_alarm()
                return True
            log(f"Success: match {match_id} added to cart with category {category}")
            play_cart_success_alarm()
            return True

        log(f"No confirmation for category {category}, trying next")

    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python autobuy_worker.py <match_id> [--test-mode]")
        sys.exit(1)

    match_id = sys.argv[1]
    test_mode = "--test-mode" in sys.argv[2:]

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            log(f"Could not connect to Chrome: {e}")
            sys.exit(1)

        contexts = browser.contexts
        if not contexts:
            log("No Chrome contexts found")
            sys.exit(1)

        context = contexts[0]
        page = context.new_page()
        page.set_viewport_size({"width": 1400, "height": 1000})

        try:
            success = attempt_match(page, match_id, test_mode=test_mode)
            if success:
                log("Worker finished successfully")
            else:
                log("Worker finished without cart success")
                try:
                    page.close()
                    log("Closed worker tab after failed attempt")
                except Exception:
                    pass
        except PlaywrightTimeout:
            log("Timeout while attempting purchase flow")
            try:
                page.close()
            except Exception:
                pass
        except Exception as e:
            log(f"Unhandled error: {e}")
            try:
                page.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
