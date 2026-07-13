"""Refresh the FIFA shop queue timer by adding and removing one available ticket.

This is a manual helper. It does not checkout or pay. It selects one available
non-accessibility row, adds it to the cart, removes it, and returns to the match
page so monitoring can continue cleanly.
"""

import argparse
import json

import main_ticket_monitor as monitor


def summarize_available(categories):
    rows = []
    for category in sorted(categories, key=monitor.refresh_cart_priority):
        if not category.get("available"):
            continue
        if monitor.is_accessibility_category(category):
            continue
        price = f"${category['price']:,.2f}" if category.get("price") is not None else "no price"
        rows.append(f"{category.get('label')} {price} qty {category.get('maxQuantity')}")
    return rows


def choose_category(categories, requested_category=None, requested_label=None):
    available = [
        category for category in categories
        if category.get("available") and not monitor.is_accessibility_category(category)
    ]

    if requested_label:
        requested = requested_label.lower()
        matches = [category for category in available if (category.get("label") or "").lower() == requested]
        return matches[0] if matches else None

    if requested_category is not None:
        wanted = f"category {requested_category}"
        normal_matches = [
            category for category in available
            if (category.get("label") or "").lower() == wanted
        ]
        if normal_matches:
            return normal_matches[0]

    return monitor.choose_refresh_category(categories)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--category",
        type=int,
        default=None,
        help="Prefer a normal category number, for example 1 or 2. Falls back to any available category.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help='Require an exact label, for example "Obstructed View Category 1".',
    )
    parser.add_argument("--match", default="target")
    args = parser.parse_args()

    matches = monitor.load_json("main_matches.json", [])
    match = next((item for item in matches if item.get("match_id") == args.match), None)
    if not match:
        raise SystemExit(f"{args.match} not found in main_matches.json")

    target = monitor.find_or_open_target(match)
    tab = monitor.CdpTab(target["webSocketDebuggerUrl"])
    try:
        state = monitor.read_page_state(tab)
        print(json.dumps({"url": state.get("url"), "title": state.get("title")}, indent=2))

        ok, health = monitor.page_health(state)
        if not ok:
            raise SystemExit(f"Page is not ready: {health}")

        categories = monitor.extract_categories(tab)
        print("available_categories=")
        print(json.dumps(summarize_available(categories), indent=2))

        category = choose_category(categories, args.category, args.label)
        if not category:
            raise SystemExit("Could not find any selectable non-accessibility ticket row")

        print("chosen_category=")
        print(json.dumps({
            "label": category.get("label"),
            "price": category.get("price"),
            "maxQuantity": category.get("maxQuantity"),
        }, indent=2))
    finally:
        tab.close()

    result = monitor.refresh_ticket_in_cart(match, category)
    print("refresh_result=")
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit("Could not complete add/remove/return refresh")


if __name__ == "__main__":
    main()
