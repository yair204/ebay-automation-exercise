# Sample run

A real run of the suite, committed so the submission includes a report without
carrying the full ~200 MB of traces and screenshots that a run produces.

| File | What it is |
|---|---|
| `report.html` | Self-contained pytest-html report for the whole suite (21 tests) |
| `junit.xml` | JUnit XML for the same run, for CI ingestion |
| `screenshots/` | The `rare_item_few_results` scenario, end to end |

## What the screenshots show

The eight screenshots follow one scenario — `vintage brass sextant`, max price
150, budget 150/item — through all four functions:

1. `search_vintage_brass_sextant_150_*` — the results page after eBay's own
   `_udhi` price filter was applied; 5 of 5 items found on one page.
2. `added_*` (five files) — each listing after "Add to cart" was confirmed, with
   variants chosen at random where the listing required them.
3. `cart_total_*` — the cart: **5 items, subtotal ILS 587.50**, asserted against
   the `150 x 5 = 750.00` threshold. This is the live cart page, reached in a run
   where eBay's bot challenge did not fire.
4. `bot_challenge_*` — for contrast, the interstitial eBay serves on the runs
   where it does fire. The framework detects it, raises a typed
   `BotChallengeError` with this screenshot attached, and the test reports a skip
   with the reason rather than a misleading failure. See README limitation 1.

## Reproducing

```bash
pytest                  # regenerates all of the above into reports/
```

Traces are written per test to `reports/traces/` and are excluded from the repo
for size. Open one with `playwright show-trace <file>.zip`.
