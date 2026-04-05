# API Findings

## Current Conclusion

We now **captured the real purchase/cart request in a successful scenario** using the HAR from match `3` (Canada vs Bosnia).

What we have today:

- static evidence from HTML / JS that points to likely internal APIs
- runtime captures from direct links
- proof that bugged flows and unavailable flows do **not** show the full useful purchase request
- a successful HAR that shows the real cart-submit flow

## Strong Static Evidence

From the ticket HTML / JS we found likely endpoints such as:

- `/ajax/selection/event/submit?lang=es`
- `/selection/event/submit?table=1`
- `/ajax/event/date/performances`
- `/ajax/event/date/range?productId=...`
- `/ajax/selection/quickbooking/updatedCart`
- `/cart/shoppingCart`
- `/tnwr/v1/...`

Likely relevant payload fields found in markup / scripts:

- `performanceId`
- `eventFormData[n].seatCategory`
- `eventFormData[n].priceLevelId`
- `eventFormData[n].advantageId`
- `eventFormData[n].quantity`

## What We Confirmed At Runtime

### Successful Real Flow Captured

Using the HAR from match `3` (`performanceId=10229226700887`), the real sequence was:

1. `GET /ajax/selection/csrf/acquire`
   - returns a plain text CSRF token
   - example token captured: `b49f3d4b-8694-4e4b-8f83-e32985208be6`

2. `GET /tnwr/v1/secure/seatmap/config/ol?...`
   - seatmap/config endpoint
   - includes headers:
     - `X-CSRF-Token: <token>`
     - `X-Secutix-Host: fwc26-shop-usd.tickets.fifa.com`
     - `X-Secutix-SecretKey: DUMMY`

3. `GET /tnwr/v1/secure/seatmap/availability?...`
   - seatmap/availability endpoint
   - same CSRF + Secutix headers

4. `POST /ajax/selection/event/submit?lang=es`
   - this is the real submit request that adds the ticket flow to cart
   - `Content-Type: application/json`
   - `X-Requested-With: XMLHttpRequest`

5. `GET /cart/shoppingCart`
   - successful follow-up navigation to cart

This is the strongest runtime evidence so far.

### Real Submit Payload Captured

Captured request:

```json
{
  "preferredAreas": {},
  "csrfToken": "b49f3d4b-8694-4e4b-8f83-e32985208be6",
  "eventFormData": [
    {
      "quantity": "1",
      "advantageId": "10229997072863",
      "priceLevelId": null,
      "seatCategory": "10229226882411",
      "audienceSubCategory": "10229393448856"
    },
    {
      "advantageId": "10229997072863",
      "priceLevelId": null,
      "seatCategory": "10229226882412",
      "audienceSubCategory": "10229393448856"
    },
    {
      "advantageId": "10229997072863",
      "priceLevelId": null,
      "seatCategory": "10229226882413",
      "audienceSubCategory": "10229393448856"
    },
    {
      "advantageId": "10229997072863",
      "priceLevelId": null,
      "seatCategory": "10229226882414",
      "audienceSubCategory": "10229393448856"
    }
  ],
  "tourId": null,
  "ballotId": null,
  "cachePage": "true",
  "performanceId": "10229226700887",
  "marketType": "MAIN"
}
```

Important behavior:

- only the chosen category had `quantity: "1"`
- the other categories were still present in the array, but without quantity
- `advantageId` was set to `10229997072863`
- `priceLevelId` was `null`
- `marketType` was `MAIN`

### Cart Success Signal Confirmed

After the submit request, the flow continued to:

- `GET /cart/shoppingCart`

So this is a reliable success indicator.

### Direct Links Work For Validation

Direct `seat/performance/...` links are useful to validate whether a match is truly unavailable.

We confirmed multiple direct pages return messages like:

- `El boleto que has seleccionado no está disponible actualmente.`
- `The ticket you have selected is currently unavailable.`

This makes direct links useful as a validation layer.

### Automated Navigation Can Trigger Queue / Logout

When scripts opened some direct links in a new tab, the site often triggered:

- `GET /ajax/selection/csrf/acquire -> 302`
- `GET /account/logout -> 302`
- redirect to `access.tickets.fifa.com` waiting room

This suggests automated navigation itself can cause a bad transition even when a human can open the same link manually.

### Existing-Tab Capture Is Better

We changed the inspection flow to attach to a tab that the user already opened manually.

This avoids some of the queue/logout behavior caused by script-driven navigation.

## What Did NOT Work

### Match 19 / unavailable real match

The match page clearly showed unavailable state.

Because the quantity / add-to-cart flow was blocked, we did not see the useful purchase submit endpoint.

### Match 86 / bugged match

The bugged match allowed:

- selecting quantity `1`
- clicking `Añadir al carrito`

But the network capture only showed analytics / ads requests like:

- Google `form_start`
- pagead / remarketing calls

It did **not** show the expected FIFA internal submit request.

Most likely explanation:

- the bugged flow is rejected before the real server-side purchase step
- or the page stops client-side before issuing the true submit

So match `86` is useful for UI testing, but **not** useful for discovering the real purchase API.

## Best Working Hypothesis

The real request we want is confirmed to be:

1. `/ajax/selection/event/submit?lang=...`

And the supporting endpoints around it are:

2. `/ajax/selection/csrf/acquire`
3. `/tnwr/v1/secure/seatmap/config/ol?...`
4. `/tnwr/v1/secure/seatmap/availability?...`
5. `/cart/shoppingCart`

## What Condition We Need Next

We already have the successful request pattern.

The next work is to turn it into an automated validator / buyer.

What still needs confirmation:

1. which `seatCategory` IDs correspond to category `1`, `2`, `3`, `4` for each match
2. whether `audienceSubCategory` is stable across matches
3. whether the same payload structure works on Argentina matches without UI interaction first
4. whether `advantageId` is always `10229997072863` or depends on URL/session

## Prepared Tooling

The repo now has:

- `inspect_api.py`

Recommended usage once a valid match is found:

```bash
python inspect_api.py --match 86 --use-existing-tab
```

or whatever real match is open in the debug Chrome.

Generated outputs:

- `api_inspection_match_<id>.json`
- `api_inspection_match_<id>_summary.json`

## Practical Recommendation

Next implementation direction:

1. keep list page as the initial signal
2. validate with direct page only if needed
3. move the worker from DOM clicking to API-driven submit using:
   - `csrf/acquire`
   - `ajax/selection/event/submit`
4. use `GET /cart/shoppingCart` as success confirmation

This should be faster and less fragile than clicking the DOM.

## Next Trigger

The next useful event is:

**Map the Argentina match category IDs and try the same submit flow automatically.**
