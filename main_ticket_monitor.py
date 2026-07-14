"""Monitor ordinary FIFA World Cup 2026 ticket pages through raw Chrome CDP.

The ordinary shop sits behind queue/captcha/login. This script does not bypass
that flow; it attaches to Chrome after a human has opened the browser profile.

This version intentionally avoids Playwright's connect_over_cdp because Chrome
150 currently returns "Browser context management is not supported" for that
path in this local setup.
"""

import argparse
import base64
import hashlib
import json
import os
import random
import re
import socket
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

CDP_BASE = os.environ.get("FIFA_CDP_BASE", "http://127.0.0.1:9222")
MATCHES_FILE = "main_matches.json"
STATE_FILE = "main_ticket_monitor_state.json"
DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_REFRESH_CART_SECONDS = 45


class CdpTab:
    def __init__(self, websocket_url):
        self.websocket_url = websocket_url
        self.sock = None
        self.next_id = 1
        self.connect()

    def connect(self):
        parsed = urlparse(self.websocket_url)
        if parsed.scheme != "ws":
            raise RuntimeError(f"Only ws:// CDP endpoints are supported: {self.websocket_url}")

        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query

        key = base64.b64encode(os.urandom(16)).decode()
        sock = socket.create_connection((host, port), timeout=10)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if b" 101 " not in response or expected.encode() not in response:
            raise RuntimeError(f"CDP WebSocket handshake failed: {response[:300]!r}")
        self.sock = sock

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def _send_frame(self, payload):
        data = payload.encode()
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self.sock.sendall(header + masked)

    def _recv_frame(self):
        first = self.sock.recv(2)
        if len(first) < 2:
            raise RuntimeError("CDP socket closed")
        opcode = first[0] & 0x0F
        masked = first[1] & 0x80
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.sock.recv(8))[0]
        mask = self.sock.recv(4) if masked else b""
        payload = b""
        while len(payload) < length:
            chunk = self.sock.recv(length - len(payload))
            if not chunk:
                raise RuntimeError("CDP socket closed mid-frame")
            payload += chunk
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("CDP socket closed by browser")
        if opcode not in (0x1, 0x2):
            return None
        return payload.decode()

    def command(self, method, params=None, timeout=10):
        command_id = self.next_id
        self.next_id += 1
        self._send_frame(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self._recv_frame()
            if not message:
                continue
            data = json.loads(message)
            if data.get("id") == command_id:
                if "error" in data:
                    raise RuntimeError(f"CDP {method} failed: {data['error']}")
                return data.get("result", {})
        raise TimeoutError(f"Timed out waiting for CDP {method}")

    def evaluate(self, expression, timeout=10):
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
            timeout=timeout,
        )
        remote = result.get("result", {})
        if "value" in remote:
            return remote["value"]
        return None


def load_json(path, default):
    file_path = Path(path)
    if not file_path.exists():
        return default
    try:
        data = json.loads(file_path.read_text())
        return data if data is not None else default
    except Exception:
        return default


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True))


def extract_performance_id(url):
    match = re.search(r"/performance/(\d+)", url)
    return match.group(1) if match else None


def get_targets():
    return requests.get(f"{CDP_BASE}/json/list", timeout=5).json()


def open_target(url):
    encoded = quote(url, safe=":/?&=,")
    response = requests.put(f"{CDP_BASE}/json/new?{encoded}", timeout=10)
    if response.status_code >= 400:
        response = requests.get(f"{CDP_BASE}/json/new?{encoded}", timeout=10)
    response.raise_for_status()
    return response.json()


def activate_target(target_id):
    try:
        requests.get(f"{CDP_BASE}/json/activate/{target_id}", timeout=3)
    except Exception:
        pass


def is_fifa_human_gate_url(url):
    lower = (url or "").lower()
    return (
        "auth.fifa.com" in lower
        or "access.tickets.fifa.com" in lower
        or "login" in lower
        or "verification" in lower
    )


def is_fifa_ticketing_url(url):
    lower = (url or "").lower()
    return (
        "fwc26-shop-usd.tickets.fifa.com" in lower
        or "auth.fifa.com" in lower
        or "access.tickets.fifa.com" in lower
    )


def find_or_open_target(match):
    performance_id = match.get("performance_id") or extract_performance_id(match["url"])
    targets = [target for target in get_targets() if target.get("type", "page") == "page"]

    for target in targets:
        target_url = target.get("url", "")
        if performance_id and performance_id in target_url:
            activate_target(target.get("id"))
            return target

    for target in targets:
        target_url = target.get("url", "")
        if is_fifa_human_gate_url(target_url):
            activate_target(target.get("id"))
            return target

    for target in targets:
        target_url = target.get("url", "")
        if is_fifa_ticketing_url(target_url):
            activate_target(target.get("id"))
            return target

    target = open_target(match["url"])
    time.sleep(2)
    return target


def navigate(tab, url):
    tab.command("Page.navigate", {"url": url}, timeout=10)


def reload_page(tab):
    try:
        tab.command("Page.reload", {"ignoreCache": True}, timeout=10)
    except Exception:
        pass


def read_page_state(tab):
    return tab.evaluate(
        r"""
        (() => ({
          url: window.location.href,
          text: document.body ? document.body.innerText : "",
          title: document.title || ""
        }))()
        """,
        timeout=10,
    ) or {"url": "", "text": "", "title": ""}


def page_health(state):
    content = (state.get("text") or "").lower()
    url = (state.get("url") or "").lower()

    if "auth.fifa.com" in url:
        return False, "LOGIN_REQUIRED"
    if "access.tickets.fifa.com" in url:
        return False, "WAITING_ROOM"
    if "captcha" in content and "submit" in content:
        return False, "CAPTCHA"
    if "critical request has been detected" in content:
        return False, "AKAMAI_BLOCK"
    if "login" in url or "verification" in content:
        return False, "LOGIN_OR_VERIFICATION"
    if "/secure/selection/event/seat/performance/" in url:
        return True, "MATCH_PAGE"
    return True, "LOADED"


def extract_categories(tab):
    return tab.evaluate(
        r"""
        (() => {
          const normalize = (value) =>
            (value || "")
              .normalize("NFD")
              .replace(/[\u0300-\u036f]/g, "")
              .replace(/\s+/g, " ")
              .trim();

          const rows = [...document.querySelectorAll("tr, li, section, article, .table_container > div, .seat_category, .tariff, body *")]
            .map((node) => {
              const text = normalize(node.innerText);
              if (!text || text.length > 600) return null;
              if (!/(category|categoria|easy access|last minute|currently unavailable|add to cart|price per item|quantity)/i.test(text)) return null;

              const labelMatch = /((?:Easy Access Standard|Wheelchair & Easy Access Amenity|Obstructed View)\s*-?\s*)?(Category|Categoria)\s+(\d+)/i.exec(text);
              if (!labelMatch) return null;
              const prefix = labelMatch[1] ? `${labelMatch[1].replace(/\s*-?\s*$/, "")} ` : "";
              const label = `${prefix}Category ${labelMatch[3]}`;

              const priceMatch = /(?:From\s*)?([\d,]+(?:\.\d{2})?)\s*USD/i.exec(text);
              const unavailable = /currently unavailable|no disponible|not available/i.test(text);

              let maxQuantity = 0;
              const selects = [...node.querySelectorAll("select")];
              for (const select of selects) {
                for (const option of select.options || []) {
                  const number = Number((option.value || option.textContent || "").trim());
                  if (Number.isFinite(number)) maxQuantity = Math.max(maxQuantity, number);
                }
              }

              return {
                label,
                text,
                priceText: priceMatch ? priceMatch[1] : null,
                price: priceMatch ? Number(priceMatch[1].replace(/,/g, "")) : null,
                maxQuantity,
                unavailable,
                available: !unavailable && maxQuantity > 0
              };
            })
            .filter(Boolean);

          const deduped = [];
          const seen = new Set();
          for (const row of rows) {
            const key = `${row.label}|${row.price}|${row.unavailable}|${row.maxQuantity}`;
            if (seen.has(key)) continue;
            seen.add(key);
            deduped.push(row);
          }
          return deduped.slice(0, 40);
        })()
        """,
        timeout=10,
    ) or []


def category_matches_rule(category, match):
    watched = match.get("categories") or ["any"]
    watched_lower = [str(item).lower() for item in watched]
    label = category.get("label", "")
    label_lower = label.lower()
    watched_any = any(item == "any" for item in watched_lower)

    is_accessibility = "easy access" in label_lower or "wheelchair" in label_lower
    watches_accessibility = any("easy access" in item or "wheelchair" in item for item in watched_lower)
    if is_accessibility and not watched_any and not watches_accessibility:
        return False

    if not watched_any and not any(item in label_lower for item in watched_lower):
        return False

    max_price = match.get("max_price")
    price = category.get("price")
    if max_price is not None and price is not None and price > float(max_price):
        return False

    return category.get("available") is True


def category_priority(category):
    label = category.get("label", "")
    priority = {
        "Category 4": 10,
        "Obstructed View Category 3": 20,
        "Category 3": 30,
        "Obstructed View Category 2": 40,
        "Obstructed View Category 1": 50,
    }
    return priority.get(label, 100)


def should_auto_cart(match):
    return bool(match.get("auto_cart") or match.get("auto_buy"))


def sorted_cart_candidates(result):
    return sorted(
        result.get("matches", []),
        key=lambda category: (
            category_priority(category),
            category.get("price") if category.get("price") is not None else 999999,
            category.get("label", ""),
        ),
    )


def select_category_quantity(tab, category):
    label_json = json.dumps(category.get("label", ""))
    return tab.evaluate(
        f"""
        (() => {{
          const desiredLabel = {label_json};
          const normalize = (value) =>
            (value || "")
              .normalize("NFD")
              .replace(/[\\u0300-\\u036f]/g, "")
              .replace(/\\s+/g, " ")
              .trim();
          const desired = normalize(desiredLabel);
          const numberMatch = /Category\\s+(\\d+)/i.exec(desired);
          const categoryNumber = numberMatch ? numberMatch[1] : null;
          const wantsObstructed = /Obstructed View/i.test(desired);
          const wantsEasy = /Easy Access Standard/i.test(desired);
          const wantsWheelchair = /Wheelchair/i.test(desired);
          const wantsPlain = !wantsObstructed && !wantsEasy && !wantsWheelchair;

          const rowNodes = [...document.querySelectorAll("tr, li, section, article, .seat_category, .tariff, .table_container > div, body *")];
          const candidates = [];
          for (const node of rowNodes) {{
            const text = normalize(node.innerText);
            if (!text || text.length > 900) continue;
            if (!categoryNumber || !new RegExp(`Category\\\\s+${{categoryNumber}}(?!\\\\d)`, "i").test(text)) continue;
            if (!/Last Minute Sales/i.test(text)) continue;
            if (/currently unavailable|not available|no disponible/i.test(text)) continue;

            const hasObstructed = /Obstructed View/i.test(text);
            const hasEasy = /Easy Access Standard/i.test(text);
            const hasWheelchair = /Wheelchair/i.test(text);
            if (wantsObstructed !== hasObstructed) continue;
            if (wantsEasy !== hasEasy) continue;
            if (wantsWheelchair !== hasWheelchair) continue;
            if (wantsPlain && (hasObstructed || hasEasy || hasWheelchair)) continue;

            const select = node.querySelector("select");
            if (!select) continue;
            const values = [...select.options].map((option) => Number((option.value || option.textContent || "").trim()));
            if (!values.some((value) => value >= 1)) continue;
            candidates.push({{ node, select, text }});
          }}

          candidates.sort((a, b) => a.text.length - b.text.length);
          const candidate = candidates[0];
          if (!candidate) {{
            return {{ ok: false, reason: "row_not_found", desiredLabel }};
          }}

          const option = [...candidate.select.options].find((item) => Number((item.value || item.textContent || "").trim()) === 1);
          if (!option) {{
            return {{ ok: false, reason: "quantity_1_option_not_found", desiredLabel, rowText: candidate.text.slice(0, 260) }};
          }}

          candidate.select.scrollIntoView({{ block: "center", inline: "center" }});
          candidate.select.focus();

          const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;
          nativeSetter.call(candidate.select, option.value);
          option.selected = true;

          for (const eventName of ["pointerdown", "mousedown", "input", "change", "mouseup", "click", "blur"]) {{
            const event = eventName === "input"
              ? new InputEvent(eventName, {{ bubbles: true, inputType: "insertText", data: option.value }})
              : new Event(eventName, {{ bubbles: true }});
            candidate.select.dispatchEvent(event);
          }}

          return new Promise((resolve) => {{
            window.setTimeout(() => {{
              const selectedValue = candidate.select.value;
              resolve({{
                ok: selectedValue === option.value,
                reason: selectedValue === option.value ? "selected" : "selection_did_not_stick",
                desiredLabel,
                selectedValue,
                expectedValue: option.value,
                rowText: normalize(candidate.node.innerText).slice(0, 260)
              }});
            }}, 350);
          }});
        }})()
        """,
        timeout=10,
    ) or {"ok": False, "reason": "no_eval_result"}


def click_add_to_cart(tab):
    return tab.evaluate(
        r"""
        (() => {
          const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
          const controls = [...document.querySelectorAll("button, input[type='button'], input[type='submit'], a")];
          const button = controls.find((node) => {
            const text = normalize(node.innerText || node.value || node.getAttribute("aria-label") || "");
            return /^add to cart$/i.test(text) && !node.disabled && node.getAttribute("aria-disabled") !== "true";
          });
          if (!button) return { ok: false, reason: "add_to_cart_button_not_found" };
          button.click();
          return { ok: true, buttonText: normalize(button.innerText || button.value || "") };
        })()
        """,
        timeout=10,
    ) or {"ok": False, "reason": "no_eval_result"}


def add_ticket_to_cart(match, category):
    target = find_or_open_target(match)
    tab = CdpTab(target["webSocketDebuggerUrl"])
    try:
        state = read_page_state(tab)
        current_url = state.get("url") or ""
        target_performance_id = extract_performance_id(match["url"])
        if target_performance_id and target_performance_id not in current_url:
            navigate(tab, match["url"])
            time.sleep(3)
            state = read_page_state(tab)

        ok, health = page_health(state)
        if not ok:
            return {"ok": False, "reason": health, "url": state.get("url") or ""}

        selected = select_category_quantity(tab, category)
        if not selected.get("ok"):
            return {"ok": False, "reason": selected.get("reason", "select_failed"), "select": selected}

        time.sleep(1.5)
        clicked = click_add_to_cart(tab)
        if not clicked.get("ok"):
            return {"ok": False, "reason": clicked.get("reason", "click_failed"), "select": selected, "click": clicked}

        time.sleep(5)
        final_state = read_page_state(tab)
        final_text = final_state.get("text") or ""
        final_url = final_state.get("url") or ""
        in_cart = "/cart/" in final_url.lower() or "your shopping cart" in final_text.lower()
        empty_cart = "shopping cart is empty" in final_text.lower()

        return {
            "ok": bool(in_cart and not empty_cart),
            "reason": "cart_updated" if in_cart and not empty_cart else "cart_not_confirmed",
            "category": category.get("label"),
            "price": category.get("price"),
            "url": final_url,
            "select": selected,
            "click": clicked,
        }
    finally:
        tab.close()


def cart_state(tab):
    state = read_page_state(tab)
    text = state.get("text") or ""
    url = state.get("url") or ""
    lower_text = text.lower()
    return {
        "url": url,
        "title": state.get("title") or "",
        "in_cart": "/cart/" in url.lower() or "your shopping cart" in lower_text,
        "empty": "shopping cart is empty" in lower_text or "your shopping cart is empty" in lower_text,
    }


def click_cart_remove_button(tab):
    return tab.evaluate(
        r"""
        (() => {
          const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
          const isVisible = (node) => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
          };
          const controls = [...document.querySelectorAll("button, a, input[type='button'], input[type='submit']")];
          const candidates = controls
            .map((node) => ({
              node,
              text: normalize([
                node.innerText,
                node.textContent,
                node.value,
                node.getAttribute("aria-label"),
                node.getAttribute("title"),
                node.id,
                node.className
              ].filter(Boolean).join(" "))
            }))
            .filter(({ node, text }) =>
              text &&
              isVisible(node) &&
              !node.disabled &&
              node.getAttribute("aria-disabled") !== "true" &&
              (/^(cancel|remove)$/i.test(text) || /(delete|trash|discard|quitar|eliminar|supprimer|löschen)/i.test(text)) &&
              !/(cookie|privacy|preference)/i.test(text)
            );
          const candidate = candidates[0];
          if (!candidate) {
            return {
              ok: false,
              reason: "remove_button_not_found",
              visibleControls: controls.map((node) => normalize(node.innerText || node.textContent || node.value || node.getAttribute("aria-label") || "")).filter(Boolean).slice(0, 40)
            };
          }
          candidate.node.scrollIntoView({ block: "center", inline: "center" });
          candidate.node.click();
          return { ok: true, text: candidate.text };
        })()
        """,
        timeout=10,
    ) or {"ok": False, "reason": "no_eval_result"}


def click_cart_confirm_button(tab):
    return tab.evaluate(
        r"""
        (() => {
          const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
          const isVisible = (node) => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
          };
          const controls = [...document.querySelectorAll("button, a, input[type='button'], input[type='submit']")];
          const candidate = controls.find((node) => {
            const text = normalize(node.innerText || node.textContent || node.value || node.getAttribute("aria-label") || "");
            return isVisible(node) && !node.disabled && /^(yes|sí|si)$/i.test(text);
          });
          if (!candidate) return { ok: false, reason: "confirm_button_not_found" };
          candidate.click();
          return { ok: true, text: normalize(candidate.innerText || candidate.textContent || candidate.value || "") };
        })()
        """,
        timeout=10,
    ) or {"ok": False, "reason": "no_eval_result"}


def click_buy_now_or_cart(tab):
    return tab.evaluate(
        r"""
        (() => {
          const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
          const isVisible = (node) => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
          };
          const cartLink = document.querySelector("#goToCartButton, a[href*='cart/shoppingCart']");
          const controls = [...document.querySelectorAll("button, a, input[type='button'], input[type='submit']")];
          const candidate = cartLink || controls.find((node) => {
            const text = normalize(node.innerText || node.textContent || node.value || node.getAttribute("aria-label") || "");
            const href = node.getAttribute("href") || "";
            return isVisible(node) && !node.disabled && (
              /shopping cart|cart\/shoppingCart/i.test(text) ||
              /cart\/shoppingCart/i.test(href)
            );
          });
          if (!candidate) return { ok: false, reason: "cart_link_not_found" };
          candidate.scrollIntoView({ block: "center", inline: "center" });
          candidate.click();
          return { ok: true, text: normalize(candidate.innerText || candidate.textContent || candidate.value || candidate.getAttribute("href") || "") };
        })()
        """,
        timeout=10,
    ) or {"ok": False, "reason": "no_eval_result"}


def remove_cart_items(tab):
    attempts = []
    for _ in range(4):
        state = cart_state(tab)
        if state["in_cart"] and state["empty"]:
            return {"ok": True, "reason": "cart_empty", "attempts": attempts, "state": state}

        clicked = click_cart_remove_button(tab)
        attempts.append({"remove": clicked})
        if clicked.get("ok"):
            time.sleep(1)
            confirm = click_cart_confirm_button(tab)
            attempts[-1]["confirm"] = confirm
            time.sleep(2)

            state = cart_state(tab)
            if state["empty"]:
                return {"ok": True, "reason": "cart_empty", "attempts": attempts, "state": state}
            continue

        buy_now = click_buy_now_or_cart(tab)
        attempts[-1]["buy_now_or_cart"] = buy_now
        if not buy_now.get("ok"):
            return {"ok": False, "reason": clicked.get("reason", "remove_failed"), "attempts": attempts, "state": state}

        time.sleep(4)
        state = cart_state(tab)
        if state["in_cart"] and state["empty"]:
            return {"ok": True, "reason": "cart_empty_after_buy_now", "attempts": attempts, "state": state}

    return {"ok": False, "reason": "cart_not_empty_after_remove_attempts", "attempts": attempts, "state": cart_state(tab)}


def refresh_ticket_in_cart(match, category):
    target = find_or_open_target(match)
    tab = CdpTab(target["webSocketDebuggerUrl"])
    try:
        state = read_page_state(tab)
        current_url = state.get("url") or ""
        target_performance_id = extract_performance_id(match["url"])
        if target_performance_id and target_performance_id not in current_url:
            navigate(tab, match["url"])
            time.sleep(3)
            state = read_page_state(tab)

        ok, health = page_health(state)
        if not ok:
            return {"ok": False, "reason": health, "url": state.get("url") or ""}

        selected = select_category_quantity(tab, category)
        if not selected.get("ok"):
            return {"ok": False, "reason": selected.get("reason", "select_failed"), "select": selected}

        time.sleep(1.5)
        clicked = click_add_to_cart(tab)
        if not clicked.get("ok"):
            return {"ok": False, "reason": clicked.get("reason", "click_failed"), "select": selected, "click": clicked}

        time.sleep(5)
        added_state = cart_state(tab)
        if added_state["in_cart"] and added_state["empty"]:
            navigate(tab, match["url"])
            time.sleep(2)
            return {
                "ok": True,
                "reason": "cart_refreshed_empty_after_add",
                "category": category.get("label"),
                "price": category.get("price"),
                "select": selected,
                "click": clicked,
                "cart_state": added_state,
                "returned_url": read_page_state(tab).get("url") or "",
            }

        if not added_state["in_cart"]:
            navigate(tab, match["url"])
            time.sleep(2)
            return {
                "ok": False,
                "reason": "cart_not_confirmed",
                "category": category.get("label"),
                "price": category.get("price"),
                "select": selected,
                "click": clicked,
                "cart_state": added_state,
                "returned_url": read_page_state(tab).get("url") or "",
            }

        removed = remove_cart_items(tab)
        navigate(tab, match["url"])
        time.sleep(3)
        return_state = read_page_state(tab)

        return {
            "ok": bool(removed.get("ok")),
            "reason": "cart_refreshed_and_returned" if removed.get("ok") else removed.get("reason", "remove_failed"),
            "category": category.get("label"),
            "price": category.get("price"),
            "select": selected,
            "click": clicked,
            "cart_state": added_state,
            "remove": removed,
            "returned_url": return_state.get("url") or "",
        }
    finally:
        tab.close()


def try_auto_cart(match, result):
    attempts = []
    for category in sorted_cart_candidates(result):
        print(f"  AUTO-CART: trying {category.get('label')} ${category.get('price')} qty 1")
        attempt = add_ticket_to_cart(match, category)
        attempts.append(attempt)
        if attempt.get("ok"):
            print(f"  AUTO-CART: added {category.get('label')} to cart")
            return True, attempts
        print(f"  AUTO-CART: failed {category.get('label')} -> {attempt.get('reason')}")
    return False, attempts


REFRESH_CART_PRIORITY = [
    "Category 2",
    "Category 1",
    "Obstructed View Category 1",
    "Obstructed View Category 2",
    "Obstructed View Category 3",
    "Category 3",
    "Category 4",
]


def is_accessibility_category(category):
    label = (category.get("label") or "").lower()
    return "easy access" in label or "wheelchair" in label


def refresh_cart_priority(category):
    label = category.get("label") or ""
    try:
        priority = REFRESH_CART_PRIORITY.index(label)
    except ValueError:
        priority = 999
    price = category.get("price")
    return (priority, price if price is not None else 999999, label)


def choose_refresh_category(categories):
    available = [
        category for category in categories
        if category.get("available") and not is_accessibility_category(category)
    ]
    return sorted(available, key=refresh_cart_priority)[0] if available else None


def should_attempt_cart_refresh(match, previous, args, result):
    if args.no_refresh_cart:
        return False
    if not match.get("refresh_cart", False):
        return False
    if not result.get("ok"):
        return False
    if result.get("available"):
        return False

    last_attempt = float(previous.get("refresh_cart_last_attempt_epoch") or 0)
    return time.time() - last_attempt >= args.refresh_cart_interval


def try_refresh_cart(match, result):
    category = choose_refresh_category(result.get("categories", []))
    if not category:
        print("  REFRESH-CART: no selectable available ticket found")
        return {"ok": False, "reason": "no_available_ticket"}

    print(f"  REFRESH-CART: trying {category.get('label')} ${category.get('price')} qty 1")
    attempt = refresh_ticket_in_cart(match, category)
    if attempt.get("ok"):
        print(f"  REFRESH-CART: added, removed, and returned from {category.get('label')}")
    else:
        print(f"  REFRESH-CART: failed {category.get('label')} -> {attempt.get('reason')}")
    return attempt


def summarize_categories(categories):
    if not categories:
        return "no category rows found"
    parts = []
    for category in categories[:12]:
        status = "available" if category.get("available") else "unavailable"
        price = f"${category['price']:,.2f}" if category.get("price") is not None else "no price"
        qty = category.get("maxQuantity", 0)
        parts.append(f"{category.get('label')}: {status}, {price}, qty max {qty}")
    if len(categories) > 12:
        parts.append(f"+{len(categories) - 12} more")
    return " | ".join(parts)


def play_alarm():
    print()
    print("!" * 72)
    print("MAIN TICKET AVAILABILITY DETECTED")
    print("!" * 72)
    print()
    for _ in range(8):
        try:
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Funk.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.4)
        except Exception:
            print("\a")
            time.sleep(0.2)


def check_match(match):
    target = find_or_open_target(match)
    tab = CdpTab(target["webSocketDebuggerUrl"])
    try:
        state = read_page_state(tab)
        target_performance_id = extract_performance_id(match["url"])
        current_url = state.get("url") or ""
        on_target_page = target_performance_id and target_performance_id in current_url
        on_human_gate = is_fifa_human_gate_url(current_url)

        if not on_target_page and not on_human_gate:
            navigate(tab, match["url"])
            time.sleep(3)
            state = read_page_state(tab)
            current_url = state.get("url") or ""
            on_target_page = target_performance_id and target_performance_id in current_url
            on_human_gate = is_fifa_human_gate_url(current_url)

        if on_target_page and not on_human_gate:
            reload_page(tab)
            time.sleep(random.uniform(1.5, 3.0))
            state = read_page_state(tab)

        ok, health = page_health(state)
        categories = extract_categories(tab) if ok else []
        matches = [category for category in categories if category_matches_rule(category, match)]
        return {
            "match_id": match["match_id"],
            "name": match.get("name", match["match_id"]),
            "url": state.get("url") or "",
            "health": health,
            "ok": ok,
            "categories": categories,
            "matches": matches,
            "available": bool(matches),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        tab.close()


def print_result(result):
    timestamp = datetime.now().strftime("%H:%M:%S")
    flag = "AVAILABLE" if result["available"] else "--"
    print(f"[{timestamp}] {result['match_id']} {flag} {result['health']}")

    if result["health"] in {"LOGIN_REQUIRED", "LOGIN_OR_VERIFICATION"}:
        print("  Complete FIFA login / verification in the Chrome window; monitor will keep waiting.")
        return
    if result["health"] in {"WAITING_ROOM", "CAPTCHA"}:
        print("  Complete FIFA queue/captcha in the Chrome window; monitor will keep waiting.")
        return
    if result["health"] == "AKAMAI_BLOCK":
        print("  FIFA blocked this browser/network for now. Wait or change network/profile.")
        return

    print(f"  {summarize_categories(result['categories'])}")
    if result["matches"]:
        for category in result["matches"]:
            print(f"  MATCH: {category.get('label')} ${category.get('price')} qty {category.get('maxQuantity')}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", default=MATCHES_FILE)
    parser.add_argument("--match", default=None, help="Only monitor one match_id")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument(
        "--refresh-cart-interval",
        type=int,
        default=DEFAULT_REFRESH_CART_SECONDS,
        help="Seconds between opportunistic cart-refresh attempts. Set 0 with --no-refresh-cart to disable.",
    )
    parser.add_argument("--no-refresh-cart", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    matches = load_json(args.matches, [])
    if args.match:
        matches = [match for match in matches if match.get("match_id") == args.match]
    if not matches:
        raise SystemExit(f"No matches configured in {args.matches}")

    state = load_json(STATE_FILE, {})
    print("Monitoring ordinary FIFA tickets via raw Chrome CDP")
    for match in matches:
        print(f"  {match['match_id']}: {match.get('name')} -> {match['url']}")
    print()

    while True:
        for match in matches:
            try:
                result = check_match(match)
            except Exception as exc:
                result = {
                    "match_id": match["match_id"],
                    "health": f"ERROR: {exc}",
                    "available": False,
                    "categories": [],
                    "matches": [],
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                }
            print_result(result)

            previous = state.get(match["match_id"], {})
            became_available = result["available"] and not previous.get("available", False)
            state[match["match_id"]] = {
                "available": result["available"],
                "health": result["health"],
                "checked_at": result["checked_at"],
                "matches": result["matches"],
                "refresh_cart_last_attempt_epoch": previous.get("refresh_cart_last_attempt_epoch"),
                "refresh_cart_last_result": previous.get("refresh_cart_last_result"),
            }
            write_json(STATE_FILE, state)

            if became_available:
                cart_ok = False
                if should_auto_cart(match):
                    cart_ok, cart_attempts = try_auto_cart(match, result)
                    state[match["match_id"]]["cart_attempts"] = cart_attempts
                    state[match["match_id"]]["cart_ok"] = cart_ok
                    write_json(STATE_FILE, state)
                play_alarm()
            elif should_attempt_cart_refresh(match, previous, args, result):
                refresh_result = try_refresh_cart(match, result)
                state[match["match_id"]]["refresh_cart_last_attempt_epoch"] = time.time()
                state[match["match_id"]]["refresh_cart_last_result"] = refresh_result
                write_json(STATE_FILE, state)

        if args.once:
            return
        time.sleep(max(args.interval + random.uniform(-5, 5), 10))


if __name__ == "__main__":
    main()
