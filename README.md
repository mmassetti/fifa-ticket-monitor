# FIFA 2026 Ordinary Ticket Monitor

Monitor for ordinary FIFA World Cup 2026 tickets on the official FIFA ticketing shop.

This project attaches to a real Chrome session through Chrome DevTools Protocol (CDP). Queue, captcha, login, and verification-code steps stay human-driven; after access is granted, the monitor keeps watching the live match page from that same browser session.

## Current Target

The default config watches this match page:

```text
https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/table/1/lang/en
```

## What It Does

- Opens or reuses a Chrome debug profile.
- Reads the official FIFA ticket page directly from the browser session.
- Detects ticket category availability and prices.
- Ignores expensive normal `Category 1` and `Category 2` tickets for the target alert.
- Watches cheap target categories:
  - `Category 3`
  - `Category 4`
  - `Obstructed View Category`
- When a target category appears, adds 1 matching ticket to the cart and leaves it there.
- Plays a local alarm when target availability is detected.
- Keeps the shop timer alive by opportunistically adding one available non-accessibility ticket, removing it from the cart, and returning to the match page.

It does **not** bypass captcha, login, queue, payment, checkout, or FIFA account verification.

## Two Cart Flows

There are two intentionally different cart behaviors:

1. **Target auto-cart**

   Used when a watched cheap category appears. The monitor adds 1 ticket to the cart and leaves it there so you can take over manually.

2. **Refresh keepalive**

   Used only when no watched cheap category is available. The monitor adds any selectable non-accessibility ticket, removes it from the cart, and navigates back to the match page. If there is no selectable ticket, it logs the miss and keeps monitoring.

## Quick Start

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the monitor:

```bash
./run_main_monitor.sh
```

If FIFA shows queue, captcha, login, or verification, complete it manually in the Chrome window. Leave the script running; it will reuse that same browser session.

## Configuration

Edit `main_matches.json` to change the target match, watched categories, max price, auto-cart, or refresh behavior.

Default rule:

```json
{
  "categories": ["Category 3", "Category 4", "Obstructed View Category"],
  "max_price": 2000,
  "auto_cart": true,
  "refresh_cart": true
}
```

Target auto-cart priority is:

1. `Category 4`
2. `Obstructed View Category 3`
3. `Category 3`
4. `Obstructed View Category 2`
5. `Obstructed View Category 1`

Refresh keepalive priority is:

1. `Category 2`
2. `Category 1`
3. `Obstructed View Category 1`
4. `Obstructed View Category 2`
5. `Obstructed View Category 3`
6. `Category 3`
7. `Category 4`

Accessibility rows such as `Easy Access` and `Wheelchair` are ignored unless explicitly added to the config.

## Useful Commands

Run one check:

```bash
python3 main_ticket_monitor.py --once
```

Run every 30 seconds:

```bash
python3 main_ticket_monitor.py --interval 30
```

Run with a custom refresh interval:

```bash
python3 main_ticket_monitor.py --interval 30 --refresh-cart-interval 240
```

Disable automatic refresh keepalive:

```bash
python3 main_ticket_monitor.py --no-refresh-cart
```

Start only the Chrome debug profile:

```bash
./start_main_chrome.sh
```

Run the manual refresh helper once:

```bash
python3 refresh_queue_timer.py
```

Prefer a normal category if available:

```bash
python3 refresh_queue_timer.py --category 1
```

Require an exact label:

```bash
python3 refresh_queue_timer.py --label "Obstructed View Category 1"
```

## Notes

- Keep Chrome open while monitoring.
- If the script is already running and code/config changed, restart it with `Ctrl+C` and `./run_main_monitor.sh`.
- Target auto-cart does not pay or complete checkout; it only leaves the wanted ticket in the cart.
- Refresh keepalive does not pay or complete checkout; it adds and removes a temporary ticket.
- See `main_ticket_monitor.md` for more detailed operational notes.
