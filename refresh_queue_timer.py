"""Refresh the FIFA shop queue timer by adding one available ticket to cart.

This is a manual helper. It does not checkout or pay. By default it chooses any
available non-accessibility row, because FIFA availability can move between
categories while the queue timer keeps counting down.
"""

import argparse
import json
import re
import time

import main_ticket_monitor as monitor


DEFAULT_PRIORITY = [
    "Category 2",
    "Category 1",
    "Obstructed View Category 1",
    "Obstructed View Category 2",
    "Obstructed View Category 3",
    "Category 3",
    "Category 4",
]


def is_accessibility(category):
    label = (category.get("label") or "").lower()
    return "easy access" in label or "wheelchair" in label


def category_sort_key(category):
    label = category.get("label") or ""
    try:
        priority = DEFAULT_PRIORITY.index(label)
    except ValueError:
        priority = 999
    price = category.get("price")
    return (priority, price if price is not None else 999999, label)


def choose_category(categories, requested_category=None, requested_label=None):
    available = [
        category for category in categories
        if category.get("available") and not is_accessibility(category)
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

    return sorted(available, key=category_sort_key)[0] if available else None


def summarize_available(categories):
    rows = []
    for category in sorted(categories, key=category_sort_key):
        if not category.get("available"):
            continue
        if is_accessibility(category):
            continue
        price = f"${category['price']:,.2f}" if category.get("price") is not None else "no price"
        rows.append(f"{category.get('label')} {price} qty {category.get('maxQuantity')}")
    return rows


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

        selected = monitor.select_category_quantity(tab, category)
        print("select_result=")
        print(json.dumps(selected, indent=2))
        if not selected or not selected.get("ok"):
            raise SystemExit("Could not select ticket quantity")

        time.sleep(2)
        clicked = monitor.click_add_to_cart(tab)
        print("click_result=")
        print(json.dumps(clicked, indent=2))
        if not clicked or not clicked.get("ok"):
            raise SystemExit("Could not click Add to cart")

        time.sleep(5)
        final_state = monitor.read_page_state(tab)
        body = final_state.get("text") or ""
        excerpt = re.sub(r"\s+", " ", body)[:1600]
        print("final_state=")
        print(json.dumps({
            "url": final_state.get("url"),
            "title": final_state.get("title"),
            "cart": "shopping cart" in body.lower() or "/cart/" in (final_state.get("url") or "").lower(),
            "body_excerpt": excerpt,
        }, indent=2))
    finally:
        tab.close()


if __name__ == "__main__":
    main()
