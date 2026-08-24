# eBay E2E Automation — Playwright + Python

An end-to-end suite against eBay: search with a price condition, add the matching
items to the cart, and assert the cart total stays within budget. Built as a Page
Object Model with a data-driven test layer.

---

## Quick start

Requires Python 3.11+ (developed on 3.13).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Run everything:

```bash
pytest
```

Run only the fast offline tests (no network, ~25s):

```bash
pytest -m unit
```

Run the live end-to-end scenario:

```bash
pytest -m e2e
```

Run a single data-driven scenario, headed, with a fixed RNG seed:

```bash
PROFILE=local pytest -k shoes_under_220 --seed 42
```

---

## Architecture

```
config/          config.yaml + per-profile overlays (ci, local)
data/            test_data.json — the Data-Driven scenario inputs
src/
  core/          framework primitives, no eBay knowledge
    config.py            typed config: YAML -> profile overlay -> ENV
    browser_factory.py   Playwright lifecycle (browser/context/tracing)
    base_page.py         POM base: navigation, locator resolution, artifacts
    price_parser.py      currency/format-tolerant price parsing
    logger.py            one logging entry point
  pages/         one class per page, selectors live here and nowhere else
    home_page.py  search_results_page.py  item_page.py  cart_page.py  login_page.py
  flows/
    shopping_flow.py     the four business functions; orchestrates page objects
tests/           pytest layer: assertions only, no Playwright calls
  fixtures/      local HTML replicas for offline verification
conftest.py      fixtures + data-driven parametrization
```

**The layering rule:** selectors exist only in `src/pages`, business orchestration
only in `src/flows`, assertions only in `tests`. A test never touches a Playwright
API directly, and a page object never knows what "budget" means. This is what
keeps each layer independently changeable when eBay's markup shifts.

`ShoppingFlow` is the facade the tests talk to, exposing the four required
functions:

| Function | Location |
|---|---|
| `authenticate()` | `shopping_flow.py` → `LoginPage` |
| `search_items_by_name_under_price(query, max_price, limit=5)` | `shopping_flow.py` → `SearchResultsPage` |
| `add_items_to_cart(urls)` | `shopping_flow.py` → `ItemPage` |
| `assert_cart_total_not_exceeds(budget_per_item, items_count)` | `shopping_flow.py` → `CartPage` |

### Design notes

**Ranked selector lists.** eBay serves several markup variants for the same page.
Rather than one brittle selector, each page object declares a *ranked tuple* and
`BasePage.first_visible()` picks whichever is live. New layouts are absorbed by
appending to a tuple.

**XPath for item extraction, as specified.** Result cards are located with
`//li[contains(@class,'s-item') or contains(@class,'s-card')][.//a[contains(@href,'/itm/')]]`,
with a CSS fallback if it yields nothing.

**Paging.** `search_items_detailed` collects matches from the current page, then
follows "Next" until it reaches `limit` or the pages run out, bounded by
`runtime.max_pages_to_scan`. Returning fewer than `limit` — including zero — is a
valid result, not a failure.

**Price parsing.** `PriceParser` handles `$24.99`, `US $1,299.00`, `GBP 15.00`,
European grouping (`$1.234,56`), and ranges (`$18.50 to $32.00`, where the lowest
price is taken). Covered by 12 unit tests.

**Random variant selection.** eBay's variant widget is a custom listbox whose
underlying `<select>` is a hidden shell carrying index values and no text, so it
cannot be driven with `select_option`. `ItemPage` drives the visible
`button.listbox-button__control` / `[role=option]` controls instead, re-scanning
after every pick because choosing a value re-renders the whole widget. The RNG is
injected, so `--seed` makes a run reproducible.

**Data-Driven.** `pytest_generate_tests` parametrizes any test requesting the
`scenario` fixture from `data/test_data.json`. Point it elsewhere with
`--data-file`. Configuration resolves as **ENV > profile YAML > base YAML**, so
the same suite runs locally and in CI without code changes.

**Reporting.** Every run writes an HTML report, JUnit XML, and Allure results,
plus per-item screenshots, a failure screenshot, and a Playwright trace per test.

---

## Reports

```bash
pytest                                   # writes all three
open reports/report.html                 # self-contained HTML
allure serve reports/allure-results      # Allure (requires the allure CLI)
playwright show-trace reports/traces/<test-name>.zip
```

| Artifact | Path |
|---|---|
| HTML report | `reports/report.html` |
| JUnit XML | `reports/junit.xml` |
| Allure results | `reports/allure-results/` |
| Screenshots | `reports/screenshots/` |
| Traces | `reports/traces/` |

**A committed sample run** lives in [`reports/sample-run/`](reports/sample-run/) —
the HTML report, the JUnit XML, and eight screenshots following one scenario
through all four functions, including the live cart at `ILS 587.50`. Everything
else under `reports/` is regenerated per run and excluded for size.

---

## Assumptions and limitations

**1. The cart page is intermittently behind eBay's bot verification.**

This is the main environmental caveat. Navigating to `cart.ebay.com` is
*sometimes* redirected to `/splashui/captcha` — "Please verify yourself to
continue". Two consecutive full-suite runs gave different results:

| Run | Cart scenarios reached | Skipped by the challenge |
|---|---|---|
| 1 | 0 / 3 | 3 |
| 2 | 1 / 3 (`rare_item_few_results`) | 2 |

So the live cart path **does** work end to end when the challenge does not fire —
run 2 read a real subtotal of `587.50` and asserted it against the
`150 x 5 = 750.00` threshold. The block is intermittent, not absolute, and it is
unrelated to which scenario is running.

Adding to the cart is never the problem: it succeeds every time and is
independently verifiable (eBay's own header counter increments and the button
flips to "See in cart"). Only the subsequent cart *page load* is challenged.

Solving or bypassing a captcha is deliberately out of scope. So:

* `BasePage.raise_if_bot_challenge()` detects the interstitial and raises a typed
  `BotChallengeError` with a screenshot, so a blocked run is never mistaken for a
  product bug. The E2E test reports it as a **skip** with the reason attached.
* The logic of `assert_cart_total_not_exceeds` is verified deterministically in
  `tests/test_cart_assertion_offline.py`, which drives the **real** `CartPage` and
  `ShoppingFlow` against a local replica of eBay's cart markup
  (`tests/fixtures/cart.html`) — covering the within-budget pass, the
  over-budget `CartTotalExceededError`, and threshold scaling by item count.

Run from an IP or browser profile eBay trusts, the live path executes unchanged —
no code change is needed, as run 2 demonstrates. Re-running is often enough.

**2. Authentication defaults to a guest session.** eBay guards its sign-in form
with the same bot challenge. `AUTH_STRATEGY=guest` (the default) establishes and
verifies an anonymous session; the cart works fine for a guest. A real login is
implemented in `LoginPage._sign_in()` and is used with
`AUTH_STRATEGY=credentials` plus `EBAY_USER` / `EBAY_PASS`, but it will usually
hit the challenge and report `bot challenge presented` rather than pretending to
succeed.

**3. Currency is whatever the site serves.** eBay geolocates: the same run showed
prices in ILS from one location and USD from another, and the price-filter
aria-labels are localised with it (`Maximum value ILS220`). Selectors match by
prefix rather than by an exact currency string. Because both sides of the
comparison — the item prices and the cart subtotal — are read from the same
rendered page, the budget assertion is internally consistent in any currency. It
is *not* a cross-currency conversion.

**4. The eBay home page frequently returns an error page** to automated requests.
`HomePage.search()` probes the header search box briefly and falls back to the
results URL, which is also where eBay's own `_udhi` price filter is applied. This
turned a 30-second dead wait into ~2 seconds.

**5. A placeholder promo card** ("Shop on eBay") is injected as the first search
result on every SRP. It has a valid `/itm/` href and a price, so it is filtered
out by title.

**6. Listings without an "Add to cart" control** (auction-only, sold out) are
recorded with `added=False` and skipped rather than aborting the run. The cart
assertion then uses the count of items actually added.

**7. Search relevance is eBay's.** A query for `shoes` under a low price cap
legitimately returns shoelaces and insoles. The suite asserts the price
condition, the result count, and uniqueness — not semantic relevance.

---

## Verified run

Two consecutive full runs of the whole suite (21 tests, ~9 min each):

```
run 1:  18 passed, 3 skipped
run 2:  19 passed, 2 skipped
```

Every skip is the documented cart challenge, reported with its reason and a
screenshot path. Sample from the `shoes_under_220` scenario:

```
search 'shoes' <= 220.00 -> 5/5 items on 1 page
[1/5] Quick Dry Aqua Socks    | variants {'color': 'Black', 'size': 'UK 7.5-8.5'}   | added=True
[2/5] Half Round Shoelaces    | variants {'color': 'dark beige', 'size': '180cm'}   | added=True
[3/5] SNORS Shoelaces         | variants {'Länge': '90 cm', 'Farbe': 'Creme', ...}  | added=True
[4/5] ECCO Leather Insoles    | variants {'Color': 'Brown', 'Size': 'US15-15.5'}    | added=True
[5/5] Vibram FiveFingers      | variants {'Color': 'Black', 'Size': '39'}           | added=True
```

And the full live path, including the cart, from `rare_item_few_results` in run 2:

```
search 'vintage brass sextant' <= 150.00 -> 5/5 items on 1 page
5 items added to the cart
Cart amount read from the page: 587.50
Cart subtotal 587.50 <= threshold 750.00 - OK
```
