# FIFA 2026 Ordinary Ticket Monitor

Monitor for ordinary FIFA World Cup 2026 tickets on the official FIFA ticketing shop.

This project attaches to a real Chrome session through Chrome DevTools Protocol (CDP). That means queue, captcha, login, and verification-code steps stay human-driven, while the monitor can keep watching the live match page after access is granted.

## Current Target

The default config watches this match page:

```text
https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/table/1/lang/en
```

## What It Does

- Opens or reuses a Chrome debug profile.
- Reads the official FIFA ticket page directly from the browser session.
- Detects ticket category availability and prices.
- Ignores expensive normal `Category 1` and `Category 2` tickets.
- Watches cheap categories:
  - `Category 3`
  - `Category 4`
  - `Obstructed View Category`
- Attempts to add 1 matching cheap ticket to the cart when availability appears.
- Plays a local alarm when availability is detected.
- Keeps the shop timer alive by opportunistically adding one available ticket to the cart when no watched cheap category is available.

It does **not** bypass captcha, login, queue, payment, checkout, or FIFA account verification.

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

Edit `main_matches.json` to change the target match, watched categories, max price, or auto-cart behavior.

Default rule:

```json
{
  "categories": ["Category 3", "Category 4", "Obstructed View Category"],
  "max_price": 2000,
  "auto_cart": true
}
```

Auto-cart priority is:

1. `Category 4`
2. `Obstructed View Category 3`
3. `Category 3`
4. `Obstructed View Category 2`
5. `Obstructed View Category 1`

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

Run with a custom cart-refresh interval:

```bash
python3 main_ticket_monitor.py --interval 30 --refresh-cart-interval 240
```

Disable automatic cart refresh:

```bash
python3 main_ticket_monitor.py --no-refresh-cart
```

Start only the Chrome debug profile:

```bash
./start_main_chrome.sh
```


Refresh the shop timer by adding one currently available ticket to the cart:

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
- Auto-cart only tries to add a ticket to the cart. It does not pay or complete checkout.
- See `main_ticket_monitor.md` for more detailed operational notes.
