# Main Ticket Monitor

This monitor watches ordinary FIFA World Cup 2026 ticket pages, focused on a direct match page instead of hospitality or the old match-list page.

Current target:

```text
https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/table/1/lang/en
```

The monitor attaches to a real Chrome session through CDP. This keeps captcha, queue, login, and verification-code steps human-driven.

## One-command run

Use this for the normal flow:

```bash
./run_main_monitor.sh
```

It starts the Chrome debug profile if needed, opens the target match, waits for CDP, and then starts the monitor. If FIFA asks for queue/captcha/login, complete it in the Chrome window and leave the script running. During queue/captcha/login the monitor will reuse that same tab and avoid navigating or reloading it.

## Run manually

1. Close Chrome.
2. Start the debug Chrome:

```bash
./start_main_chrome.sh
```

3. In that Chrome, pass FIFA queue/captcha/login and open the target URL manually if needed.
4. Run one check:

```bash
python3 main_ticket_monitor.py --once
```

5. Run continuous monitoring:

```bash
python3 main_ticket_monitor.py --interval 30
```

The monitor reads `main_matches.json`, extracts category rows from the live page, and alerts when a watched category has quantity above zero and price within the rule.

## Telegram alerts

Set Telegram credentials before starting the monitor. The easiest local setup is:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:replace_me
TELEGRAM_CHAT_ID=959522546
```

When a watched category first becomes available, the monitor sends one Telegram alert for that availability event. It does not send repeat messages while the same availability remains true.

## Target auto-cart

Auto-cart is enabled for the target match in `main_matches.json`.

When a watched cheap category appears, the monitor attempts to add 1 ticket to the cart and leaves it there. This is the action path for the ticket we actually want.

Current watched categories are:

- `Category 2`
- `Category 3`
- `Category 4`
- `Obstructed View Category`

Normal `Category 1` is intentionally ignored for target alerts because it is too expensive. `Category 2` is watched up to the configured max price. Accessibility rows such as `Easy Access` and `Wheelchair` are also ignored unless explicitly added to the config.

## Refresh keepalive

Automatic cart refresh is disabled by default for now.

If re-enabled with `refresh_cart: true`, this is deliberately different from target auto-cart:

1. It only runs when the page is ready.
2. It only runs when no watched cheap category is currently available.
3. It chooses one selectable non-accessibility ticket row.
4. It adds 1 ticket to the cart.
5. It opens the cart if needed, clicks `CANCEL`, confirms `YES`, and clears that temporary ticket.
6. It navigates back to the match page and keeps monitoring.

For now, leave it disabled unless you explicitly want to experiment with it. Neither target auto-cart nor refresh keepalive checks out or pays.

Manual refresh is still available:

```bash
python3 refresh_queue_timer.py
```

Useful variants:

```bash
python3 refresh_queue_timer.py --category 1
python3 refresh_queue_timer.py --label "Obstructed View Category 1"
```

## Network/API capture

Once the target page is open in debug Chrome, capture the useful XHR calls:

```bash
python3 inspect_api.py --match target --use-existing-tab --listen-only --duration 45
```

If you manually change quantity or click add-to-cart during that window, the capture should include the SecuTix/FIFA submit calls.
