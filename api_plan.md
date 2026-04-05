# API Investigation Plan

## Goal

Replace fragile DOM-only availability detection and cart interaction with FIFA internal requests when possible.

## What We Already Know

Confirmed / likely internal endpoints:

- `/ajax/selection/csrf/acquire`
- `/ajax/selection/event/submit?lang=es`
- `/selection/event/submit?table=1`
- `/ajax/event/date/performances`
- `/ajax/event/date/range?productId=...`
- `/ajax/selection/quickbooking/updatedCart`
- `/cart/shoppingCart`
- `/tnwr/v1/config`
- `/tnwr/v1/secure/seatmap/config/ol?...`
- `/tnwr/v1/secure/seatmap/availability?...`

Important payload fields:

- `performanceId`
- `eventFormData[n].seatCategory`
- `eventFormData[n].priceLevelId`
- `eventFormData[n].advantageId`
- `eventFormData[n].quantity`
- `audienceSubCategory`
- `marketType`

## Confirmed Successful Flow (from HAR)

For match `3` (Canada vs Bosnia), the successful add-to-cart flow was:

1. `GET /ajax/selection/csrf/acquire`
2. `GET /tnwr/v1/secure/seatmap/config/ol?...`
3. `GET /tnwr/v1/secure/seatmap/availability?...`
4. `POST /ajax/selection/event/submit?lang=es`
5. `GET /cart/shoppingCart`

Confirmed request headers used by the seatmap endpoints:

- `X-CSRF-Token: <token from csrf/acquire>`
- `X-Secutix-Host: fwc26-shop-usd.tickets.fifa.com`
- `X-Secutix-SecretKey: DUMMY`

Confirmed submit characteristics:

- `Content-Type: application/json`
- `X-Requested-With: XMLHttpRequest`
- `Referer: direct seat/performance page`

## Prepared Tooling

Use:

```bash
python inspect_api.py --match 86
python inspect_api.py --match 19
```

Output files:

- `api_inspection_match_<match>.json`
- `api_inspection_match_<match>_summary.json`

The script:

- connects to Chrome on `9222`
- opens the direct match page
- clicks `Reserva el mejor sitio`
- sets quantity to `1`
- clicks `Añadir al carrito`
- captures interesting XHR/fetch/JSON responses

## When To Run It

Run it only when:

- Chrome was started with `./start_chrome.sh`
- you are already past queue/login
- the direct match page is reachable

If Chrome is stuck in queue, the script cannot capture the useful purchase API calls.

## What To Look For In The Output

Highest-value target requests:

1. `POST /ajax/selection/event/submit?lang=...`
2. `GET /cart/shoppingCart`
3. `/tnwr/v1/secure/seatmap/config/ol?...`
4. `/tnwr/v1/secure/seatmap/availability?...`
5. `/ajax/selection/quickbooking/updatedCart`
6. Any response with JSON containing:
   - `available`
   - `availability`
   - `quantity`
   - `seatCategory`
   - `priceLevelId`
   - `cart`
   - `reservation`
   - `unavailable`

## Desired End State

Best case:

- detect availability via internal API instead of DOM text
- validate a match before sounding the alarm
- submit add-to-cart via API instead of DOM clicks
- confirm success via `GET /cart/shoppingCart`

Fallback if API is messy:

- keep list page as coarse trigger
- use direct performance page + internal submit endpoint as final confirmation

## Next Action Once Out Of Queue

1. Start Chrome with `./start_chrome.sh`
2. Get past queue/login
3. Run:

```bash
python inspect_api.py --match 19
```

4. If no useful endpoint appears, run:

```bash
python inspect_api.py --match 86
```

5. Review the generated `*_summary.json` first
6. Map category IDs for Argentina matches
7. Promote the useful endpoint into the real monitor/worker
