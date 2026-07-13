# Main Ticket Monitor

This is the first monitor for ordinary FIFA World Cup 2026 tickets, focused on a direct match page instead of the old match-list page.

Current target:

```text
https://fwc26-shop-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/table/1/lang/en
```

The monitor attaches to a real Chrome session through CDP. This keeps the captcha, queue, login, and verification-code steps human-driven.

## One-command run

Use this for the normal flow:

```bash
./run_main_monitor.sh
```

It starts the Chrome debug profile if needed, opens the target match, waits for CDP, and then starts the monitor. If FIFA asks for queue/captcha/login, complete it in the Chrome window and leave the script running.

## Run

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

## Refresh queue timer

The main monitor now attempts an automatic cart refresh every 240 seconds by default. It only does this when the page is ready, no watched cheap category is currently available, and at least one non-accessibility ticket row is selectable. If no ticket is available for refresh, it logs that and keeps monitoring.

Manual refresh is still available:

```bash
python3 refresh_queue_timer.py
```

Neither flow checks out or pays.

## Network/API capture

Once the target page is open in debug Chrome, capture the useful XHR calls:

```bash
python3 inspect_api.py --match target --use-existing-tab --listen-only --duration 45
```

If you manually change quantity or click add-to-cart during that window, the capture should include the SecuTix/FIFA submit calls.

## Auto-cart

Auto-cart is enabled for the target match in `main_matches.json`.

The monitor only attempts to add one ticket to the cart when a watched cheap category appears. It does not checkout or pay. Current watched categories are:

- `Category 3`
- `Category 4`
- `Obstructed View Category`

Normal `Category 1` and `Category 2` are intentionally ignored because they are too expensive. Accessibility rows such as `Easy Access` and `Wheelchair` are also ignored unless explicitly added to the config.
