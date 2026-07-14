# Resale Seat Monitor

This monitor watches the FIFA resale seat map for the target World Cup 2026 match.

Target:

```text
https://fwc26-resale-usd.tickets.fifa.com/secure/selection/event/seat/performance/10229226725358/contact-advantages/10229997366844,10230133312745/lang/en
```

## What it does

- attaches to the same Chrome debug session as the ordinary-ticket monitor
- waits for the human-managed queue/captcha/login flow
- reads already-loaded FIFA seatmap API resources from the page
- fetches the same `/tnwr/v1/secure/seatmap/...` URLs from the browser session
- extracts concrete resale seats:
  - category
  - price
  - block
  - row
  - seat number
  - `resaleMovementId` when FIFA returns it
- sends Telegram alerts for matching seats
- stores alert state in `resale_seat_monitor_state.json`

It does not bypass captcha, login, queue, payment, checkout, or FIFA account verification.

## Run

```bash
./run_resale_seat_monitor.sh
```

If FIFA asks for queue/captcha/login, complete it in the Chrome window and leave the script running.

## Telegram

The script uses the same `.env` values as the ordinary monitor:

```bash
TELEGRAM_BOT_TOKEN=123456789:replace_me
TELEGRAM_CHAT_ID=959522546
```

## Config

Edit `resale_targets.json`.

Default target rule:

```json
{
  "categories": ["Category 3", "Category 4", "Obstructed View Category"],
  "max_price": 2000,
  "include_accessible": false,
  "auto_cart": false
}
```

## Cart status

Resale auto-cart is intentionally disabled by default.

Reason: resale uses concrete seat/movement IDs from the seat map. To make cart reliable, capture the exact submit request once by manually adding a resale seat while `resale_network_probe.user.js` is installed, then map that request into the monitor. Until that request is mapped, the safe automated behavior is alerting with the exact seat metadata.
