# Next Steps

## Current Status

- Monitor runs against the FIFA general match list page using your real Chrome via CDP.
- Direct match pages are used for action, not as primary detection, to avoid false positives.
- Auto-attempt worker opens a new tab only when a match looks available.
- Category priority is `1 -> 2 -> 3`.
- Match `86` is currently used as `test-mode` because FIFA lists it as available but rejects checkout.
- `inspect_api.py` and `api_plan.md` are prepared for capturing internal FIFA requests once the session is past queue.
- A successful HAR from match `3` confirmed the real cart flow:
  - `GET /ajax/selection/csrf/acquire`
  - `GET /tnwr/v1/secure/seatmap/config/ol?...`
  - `GET /tnwr/v1/secure/seatmap/availability?...`
  - `POST /ajax/selection/event/submit?lang=es`
  - `GET /cart/shoppingCart`
- `autobuy_worker.py` now tries an API-driven submit first and falls back to DOM clicks if the page model cannot be extracted.

## High-Value Improvements

### 1. Mobile Alerts

- Add Telegram notifications.
- Add WhatsApp notifications.
- Add email fallback.
- Optional: phone call alert via Twilio for real cart success.

### 2. More Reliable Purchase Flow

- Detect true cart success with stronger DOM checks.
- Try `Category 4` after `1 -> 2 -> 3`.
- Add alternate path using seat-map mode, not just `Best available`.
- Smarter category retry strategy instead of fixed cooldown only.

### 3. Better Monitoring / Recovery

- Detect and log `waiting room`, `captcha`, `login expired`, and `blocked` states.
- Save screenshot + HTML snapshot when monitor fails.
- Write logs to file, not only stdout.
- Restart worker automatically if a worker crashes or hangs.
- Deduplicate worker tabs / close stale tabs from previous attempts.

### 4. Faster Signals

- Inspect XHR / fetch calls on direct match pages.
- If an internal availability API can be found, monitor that directly.
- Use direct links as a second signal while keeping the general list as the primary signal.

## Automation Goal

The realistic goal is **semi-automatic**, not fully unattended.

Reason:

- FIFA may require login again.
- FIFA may ask for email code / MFA.
- FIFA may show captcha.
- FIFA may temporarily block or queue the session.

So the best setup is:

- Chrome opens automatically.
- Monitor starts automatically.
- If the session is still valid, it runs with no intervention.
- If the session expired, you log in once manually and the monitor keeps going.

## Recommended Next Build

### A. Auto-start on macOS

Set up a macOS `launchd` / `LaunchAgent` so that on login:

1. `start_chrome.sh` runs automatically.
2. Chrome opens with the FIFA profile and all required tabs.
3. After a short delay, `python fifa_monitor.py` starts automatically.

This avoids manually opening Chrome and manually launching the script every time.

### B. Reuse Real Chrome Session

- Keep using the dedicated Chrome profile directory from `start_chrome.sh`.
- If FIFA keeps the cookies valid, the monitor should continue working across restarts.
- When the session expires, just log in again in that same Chrome profile.

### C. Health Alerts

Add alerts for these states:

- `LOGIN REQUIRED`
- `WAITING ROOM`
- `BOT DETECTED`
- `ACCESS BLOCKED`

That way you know if the monitor is alive but not actually usable.

### D. Telegram Integration

Recommended message types:

- Match becomes available
- Worker opened a direct tab
- Worker added ticket to cart successfully
- Session expired / login required
- Site blocked / waiting room

## Suggested Order

1. Add file logging + health-state detection.
2. Add Telegram notifications.
3. Add macOS LaunchAgent for auto-start.
4. Improve real cart-success detection.
5. Investigate internal FIFA network/API calls for faster monitoring.

## Notes About Full Automation

Possible:

- Auto-open browser.
- Auto-start monitor.
- Auto-open tabs.
- Auto-attempt add-to-cart.

Not reliably possible without manual help:

- Solving fresh login challenges forever.
- Solving captcha forever.
- Handling every queue / anti-bot event unattended.

So the right target is:

**"Hands-off most of the time, one manual login when FIFA forces it."**

## Resale Notes

- FIFA resale now has queue / waiting-room behavior too.
- When the session timer expires, the listing query may stop working and ticket results may no longer load.
- Useful discovered workaround:
  - put any ticket in the cart
  - remove it
  - this resets the countdown timer

### Possible future automation for resale

- Detect low remaining session time.
- Automatically add any temporary ticket to cart.
- Remove it immediately.
- Use that as a session keep-alive / timer reset.

This should be treated carefully because it changes cart state and may interact with FIFA anti-bot rules.
