"""Monitor FIFA resale seatmap availability via the live Chrome session.

This does not bypass queue/captcha/login. It attaches to Chrome after the user
opens the resale page and reads the FIFA seatmap API URLs already loaded by
the page. The monitor alerts on concrete resale seats rather than category rows.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests

import main_ticket_monitor as cdp

TARGETS_FILE = "resale_targets.json"
STATE_FILE = "resale_seat_monitor_state.json"
DEFAULT_INTERVAL_SECONDS = 30


def extract_category_number(label: str | None) -> int | None:
    match = re.search(r"category\s+(\d+)", label or "", re.I)
    return int(match.group(1)) if match else None


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


def is_resale_human_gate_url(url):
    lower = (url or "").lower()
    return (
        "auth.fifa.com" in lower
        or "access.tickets.fifa.com" in lower
        or "login" in lower
        or "verification" in lower
    )


def is_resale_ticketing_url(url):
    lower = (url or "").lower()
    return (
        "fwc26-resale-usd.tickets.fifa.com" in lower
        or "auth.fifa.com" in lower
        or "access.tickets.fifa.com" in lower
    )


def find_or_open_target(match):
    performance_id = match.get("performance_id") or cdp.extract_performance_id(match["url"])
    targets = [target for target in cdp.get_targets() if target.get("type", "page") == "page"]

    for target in targets:
        target_url = target.get("url", "")
        if performance_id and "fwc26-resale-usd.tickets.fifa.com" in target_url and performance_id in target_url:
            cdp.activate_target(target.get("id"))
            return target

    for target in targets:
        target_url = target.get("url", "")
        if is_resale_human_gate_url(target_url):
            cdp.activate_target(target.get("id"))
            return target

    for target in targets:
        target_url = target.get("url", "")
        if is_resale_ticketing_url(target_url):
            cdp.activate_target(target.get("id"))
            return target

    target = cdp.open_target(match["url"])
    time.sleep(2)
    return target


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
    if "fwc26-resale-usd.tickets.fifa.com" in url and "/secure/selection/event/seat/performance/" in url:
        return True, "RESALE_MATCH_PAGE"
    return True, "LOADED"


def normalize_category_name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def seat_key(seat):
    return "|".join(
        str(seat.get(key) or "")
        for key in ["resaleMovementId", "seatId", "category", "block", "row", "number", "price"]
    )


def extract_resale_seats(tab):
    return tab.evaluate(
        r"""
        (async () => {
          const moneyFromApi = (value) => {
            if (value === null || value === undefined || value === "") return null;
            const number = Number(value);
            if (!Number.isFinite(number)) return null;
            return number / 1000;
          };

          const uniq = (items) => [...new Set(items.filter(Boolean))];
          const normalizeCategoryName = (value) => String(value || "").replace(/\s+/g, " ").trim();
          const resources = performance.getEntriesByType("resource")
            .map((entry) => entry.name || "")
            .filter((url) => /\/tnwr\/v1\/secure\/seatmap\//i.test(url));

          const availabilityUrls = uniq(resources.filter((url) => /\/availability/i.test(url))).slice(-4);
          const freeSeatUrls = uniq(resources.filter((url) => /\/seats\/free\/ol/i.test(url))).slice(-12);
          const detailUrls = uniq(resources.filter((url) => /\/seats\/detail/i.test(url))).slice(-12);

          const fetchJson = async (url) => {
            try {
              const response = await fetch(url, {
                credentials: "include",
                headers: { "accept": "application/json, text/plain, */*" },
              });
              const text = await response.text();
              if (!response.ok) return { ok: false, status: response.status, url, text: text.slice(0, 500) };
              return { ok: true, status: response.status, url, json: JSON.parse(text) };
            } catch (error) {
              return { ok: false, status: 0, url, text: String(error).slice(0, 500) };
            }
          };

          const requests = [];
          const seats = [];
          const ranges = [];

          for (const url of availabilityUrls) {
            const result = await fetchJson(url);
            requests.push({ kind: "availability", ok: result.ok, status: result.status, url });
            if (!result.ok) continue;
            for (const item of result.json?.priceRangeCategories || []) {
              ranges.push({
                id: item.id,
                category: item.name?.en || item.name?.es || item.name?.de || `Category ${item.rank || ""}`.trim(),
                rank: item.rank ?? null,
                minPrice: moneyFromApi(item.minPrice),
                maxPrice: moneyFromApi(item.maxPrice),
              });
            }
          }

          const mergeSeat = (feature, sourceUrl) => {
            const props = feature?.properties || {};
            const category = normalizeCategoryName(
              props.seatCategory?.name?.en ||
              props.seatCategory?.name?.es ||
              props.seatCategory?.name?.de ||
              props.seatCategory ||
              props.categoryName ||
              props.priceCategory?.name?.en ||
              props.priceCategory?.name ||
              "Unknown"
            );
            const block = props.block?.name?.en || props.block?.name?.es || props.block?.name?.de || props.block?.name || props.blockName || props.block || "";
            const price = moneyFromApi(props.amount ?? props.price ?? props.resaleAmount ?? props.resaleInfo?.amount);
            const coords = feature?.geometry?.coordinates || null;
            seats.push({
              category,
              categoryId: props.seatCategoryId ?? props.categoryId ?? props.priceCategoryId ?? null,
              price,
              block,
              row: props.row ?? props.rowName ?? "",
              number: props.number ?? props.seatNumber ?? "",
              seatId: props.seatId ?? props.id ?? props.uuid ?? null,
              resaleMovementId: props.resaleMovementId ?? props.movementId ?? props.resaleInfo?.resaleMovementId ?? null,
              accessible: Boolean(props.accessible || props.isAccessible || /wheelchair|easy access|accessible/i.test(category)),
              sourceUrl,
              coordinates: coords,
            });
          };

          for (const url of freeSeatUrls) {
            const result = await fetchJson(url);
            const features = result.json?.features || [];
            requests.push({ kind: "seats/free", ok: result.ok, status: result.status, count: features.length, url });
            if (!result.ok) continue;
            for (const feature of features) mergeSeat(feature, url);
          }

          for (const url of detailUrls) {
            const result = await fetchJson(url);
            requests.push({ kind: "seats/detail", ok: result.ok, status: result.status, url });
          }

          const seen = new Set();
          const dedupedSeats = [];
          for (const seat of seats) {
            const key = [
              seat.resaleMovementId,
              seat.seatId,
              seat.category,
              seat.block,
              seat.row,
              seat.number,
              seat.price
            ].join("|");
            if (seen.has(key)) continue;
            seen.add(key);
            dedupedSeats.push(seat);
          }

          dedupedSeats.sort((a, b) => (a.price ?? 999999999) - (b.price ?? 999999999));
          ranges.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));

          return {
            title: document.title || "",
            url: window.location.href,
            requests,
            ranges,
            seats: dedupedSeats,
            resourceCount: resources.length,
          };
        })()
        """,
        timeout=30,
    ) or {"requests": [], "ranges": [], "seats": []}


def category_matches(seat, match):
    watched = match.get("categories") or ["any"]
    watched_lower = [str(item).lower() for item in watched]
    category = (seat.get("category") or "").lower()
    category_number = extract_category_number(category)

    if seat.get("accessible") and not match.get("include_accessible", False):
        return False

    if not any(item == "any" for item in watched_lower):
        matched = False
        for item in watched_lower:
            if item in category:
                matched = True
                break
            number_match = re.search(r"category\s+(\d+)", item)
            if number_match and category_number == int(number_match.group(1)):
                matched = True
                break
        if not matched:
            return False

    max_price = match.get("max_price")
    price = seat.get("price")
    if max_price is not None and price is not None and price > float(max_price):
        return False

    return price is not None


def summarize_result(result):
    seats = result.get("seats") or []
    matches = result.get("matches") or []
    ranges = result.get("ranges") or []
    parts = [
        f"seats loaded={len(seats)}",
        f"matches={len(matches)}",
    ]
    if seats:
        parts.append(f"cheapest=${seats[0].get('price')}")
    if ranges:
        range_text = ", ".join(
            f"{item.get('category')}: ${item.get('minPrice')}-${item.get('maxPrice')}"
            for item in ranges[:5]
        )
        parts.append(f"ranges: {range_text}")
    return " | ".join(parts)


def format_money(value):
    return f"${value:,.2f}" if isinstance(value, (int, float)) else "no price"


def format_seat_line(seat):
    location = ", ".join(
        str(value)
        for value in [seat.get("block"), f"row {seat.get('row')}" if seat.get("row") else "", f"seat {seat.get('number')}" if seat.get("number") else ""]
        if value
    )
    base = f"- {seat.get('category')}: {format_money(seat.get('price'))}"
    if location:
        base += f" ({location})"
    if seat.get("resaleMovementId"):
        base += f" id={seat.get('resaleMovementId')}"
    return base


def telegram_is_configured():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram_message(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"ok": False, "reason": "telegram_not_configured"}

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=10,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "description": response.text[:500]}
    if not response.ok or not data.get("ok"):
        return {"ok": False, "status_code": response.status_code, "description": data.get("description", response.text[:500])}
    return {"ok": True}


def format_alert(match, result, new_matches):
    lines = [
        "FIFA 2026 resale seats available",
        f"Match: {match.get('name', match.get('match_id'))}",
        f"Health: {result.get('health')}",
        "",
        "Seats:",
    ]
    for seat in new_matches[:8]:
        lines.append(format_seat_line(seat))
    if len(new_matches) > 8:
        lines.append(f"... +{len(new_matches) - 8} more")
    lines.extend(["", match.get("url", result.get("url", ""))])
    return "\n".join(lines)


def notify_telegram(match, result, new_matches):
    if not telegram_is_configured():
        return {"ok": False, "reason": "telegram_not_configured"}
    try:
        notification = send_telegram_message(format_alert(match, result, new_matches))
    except Exception as exc:
        notification = {"ok": False, "reason": str(exc)}
    if notification.get("ok"):
        print("  TELEGRAM: sent resale alert")
    else:
        print(f"  TELEGRAM: failed -> {notification.get('reason') or notification.get('description')}")
    return notification


def play_alarm():
    print()
    print("!" * 72)
    print("RESALE SEAT AVAILABILITY DETECTED")
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
    tab = cdp.CdpTab(target["webSocketDebuggerUrl"])
    try:
        state = cdp.read_page_state(tab)
        current_url = state.get("url") or ""
        target_performance_id = match.get("performance_id") or cdp.extract_performance_id(match["url"])
        on_target_page = target_performance_id and target_performance_id in current_url and "fwc26-resale-usd" in current_url
        on_human_gate = is_resale_human_gate_url(current_url)

        if not on_target_page and not on_human_gate:
            cdp.navigate(tab, match["url"])
            time.sleep(4)
            state = cdp.read_page_state(tab)
            current_url = state.get("url") or ""
            on_target_page = target_performance_id and target_performance_id in current_url and "fwc26-resale-usd" in current_url
            on_human_gate = is_resale_human_gate_url(current_url)

        ok, health = page_health(state)
        payload = extract_resale_seats(tab) if ok and on_target_page and not on_human_gate else {"requests": [], "ranges": [], "seats": []}
        seats = payload.get("seats") or []
        matches = [seat for seat in seats if category_matches(seat, match)]
        return {
            "match_id": match["match_id"],
            "name": match.get("name", match["match_id"]),
            "url": state.get("url") or payload.get("url") or "",
            "health": health,
            "ok": ok,
            "ranges": payload.get("ranges") or [],
            "requests": payload.get("requests") or [],
            "resourceCount": payload.get("resourceCount", 0),
            "seats": seats,
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

    print(f"  {summarize_result(result)}")
    for seat in result.get("matches", [])[:8]:
        print(f"  MATCH: {format_seat_line(seat)}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", default=TARGETS_FILE)
    parser.add_argument("--match", default=None, help="Only monitor one match_id")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    targets = load_json(args.targets, [])
    if args.match:
        targets = [match for match in targets if match.get("match_id") == args.match]
    if not targets:
        raise SystemExit(f"No resale targets configured in {args.targets}")

    state = load_json(STATE_FILE, {})
    print("Monitoring FIFA resale seats via raw Chrome CDP")
    for match in targets:
        print(f"  {match['match_id']}: {match.get('name')} -> {match['url']}")
    print()

    while True:
        for match in targets:
            try:
                result = check_match(match)
            except Exception as exc:
                result = {
                    "match_id": match["match_id"],
                    "health": f"ERROR: {exc}",
                    "available": False,
                    "ranges": [],
                    "requests": [],
                    "seats": [],
                    "matches": [],
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                }
            print_result(result)

            previous = state.get(match["match_id"], {})
            previous_keys = set(previous.get("alerted_keys") or [])
            current_keys = [seat_key(seat) for seat in result.get("matches", [])]
            new_matches = [
                seat for seat in result.get("matches", [])
                if seat_key(seat) not in previous_keys
            ]

            state[match["match_id"]] = {
                "available": result["available"],
                "health": result["health"],
                "checked_at": result["checked_at"],
                "match_count": len(result.get("matches", [])),
                "cheapest_match": (result.get("matches") or [None])[0],
                "alerted_keys": sorted(previous_keys.union(current_keys))[-500:],
            }
            write_json(STATE_FILE, state)

            if new_matches:
                telegram_result = notify_telegram(match, result, new_matches)
                state[match["match_id"]]["telegram_last_result"] = telegram_result
                write_json(STATE_FILE, state)
                play_alarm()

        if args.once:
            return
        time.sleep(max(args.interval + random.uniform(-5, 5), 10))


if __name__ == "__main__":
    main()
