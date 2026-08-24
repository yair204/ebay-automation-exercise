# ReadMeAIBugs — Static review of the AI-generated test

Static analysis only: the code below was reviewed by reading, without running it
or using any tooling, as the exercise requires.

## The code under review

```python
from playwright.sync_api import sync_playwright
from selenium import webdriver
import time

def test_search_functionality():
    browser = sync_playwright().start().chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")

    time.sleep(2)

    search_box = page.locator("#search")
    search_box.fill("playwright testing")

    page.locator(".button").click()

    time.sleep(3)

    results = page.locator(".result-item")

    browser.close()
```

**Summary:** this function cannot fail. Whatever the site does, the test reports
success — which is worse than having no test at all, because it produces a green
build that nobody re-checks. Six issues are detailed below, ordered by severity.

---

## Bug 1 — The test has no assertion, so it can never fail *(critical)*

```python
results = page.locator(".result-item")
```

This is the defect that makes the whole test worthless.

`page.locator(...)` in Playwright is **lazy**. It does not touch the DOM, does not
query anything, and does not wait for anything — it merely builds a selector
object that will be resolved *if and when* an action or assertion is performed on
it. Nothing is ever performed on `results`: it is assigned to a local variable
and immediately goes out of scope when the function returns.

The practical consequence: if the search silently returns zero results, if the
`.result-item` class is renamed, or if the page renders an error, the test still
passes. The variable name `results` creates a false impression that something is
being verified.

**Fix — assert with a web-first assertion, which retries until the timeout:**

```python
from playwright.sync_api import expect

results = page.locator(".result-item")
expect(results.first).to_be_visible()          # waits for the first result to render
assert results.count() > 0, "The search returned no results"
```

`expect()` is the important part: unlike a bare `assert results.count() > 0`, it
polls until the condition holds or the timeout expires, so it is not racing the
page's rendering.

---

## Bug 2 — Playwright is started but never stopped, leaking a driver process *(high)*

```python
browser = sync_playwright().start().chromium.launch()
...
browser.close()
```

`sync_playwright().start()` spawns a **Node.js driver process** and returns a
`Playwright` object. That object is discarded immediately here: the expression is
chained straight into `.chromium.launch()`, so the only reference kept is the
`Browser`. `browser.close()` closes the browser, but the driver process is never
stopped, because there is no longer any handle on which to call `.stop()`.

Every invocation therefore leaks one Node process. In a suite of a few hundred
tests this exhausts file descriptors and memory, and the symptom shows up far
away from the cause — typically as unrelated tests timing out later in the run.

**Fix — use the context manager, which guarantees `stop()`:**

```python
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    try:
        page = browser.new_page()
        ...
    finally:
        browser.close()
```

In a pytest suite the cleaner answer is to move this into a fixture (which is
what `conftest.py` in this repository does) so that lifecycle management lives in
exactly one place instead of being repeated in every test.

---

## Bug 3 — No teardown on failure, so a failing test leaks a browser *(high)*

`browser.close()` is the last statement of a straight-line function. If **any**
statement above it raises — a failed `goto`, a selector timeout, and after Bug 1
is fixed, a failing assertion — control leaves the function immediately and
`browser.close()` never executes.

This is exactly backwards: the browser leaks precisely in the failure case, which
is also the case that occurs repeatedly while a real bug is being investigated.

**Fix — `try/finally` (as shown in Bug 2), or a fixture with teardown:**

```python
@pytest.fixture()
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser.new_page()
        finally:
            browser.close()
```

Code after `yield` in a pytest fixture runs even when the test fails.

---

## Bug 4 — `time.sleep()` instead of Playwright's auto-waiting *(high)*

```python
time.sleep(2)
...
time.sleep(3)
```

Fixed sleeps are wrong in both directions at once:

* **Too short on a slow run.** On a loaded CI machine or a cold cache, 2 seconds
  may not be enough, and the test fails for reasons that have nothing to do with
  the application. This is the classic source of "flaky" tests.
* **Too long on a fast run.** When the page is ready in 200 ms, 4.8 seconds are
  burned doing nothing. Multiplied across a suite, this dominates the runtime.

They are also redundant. Playwright's actionability checks already auto-wait: a
`fill()` or `click()` waits for the element to be attached, visible, stable, and
enabled before acting. The sleeps add nothing but delay and false confidence.

**Fix — delete the sleeps and wait for a condition, not for a duration:**

```python
page.goto("https://example.com", wait_until="domcontentloaded")

search_box = page.get_by_role("searchbox")
search_box.fill("playwright testing")          # auto-waits for actionability
page.get_by_role("button", name="Search").click()

expect(page.locator(".result-item").first).to_be_visible()   # waits for the outcome
```

---

## Bug 5 — `.button` is ambiguous and will throw a strict-mode violation *(medium)*

```python
page.locator(".button").click()
```

Two distinct problems:

1. **Strict mode.** A Playwright `Locator` is strict by default. If `.button`
   matches more than one element — and a generic class like `button` almost
   always matches several on a real page — `.click()` raises
   `Error: strict mode violation: locator('.button') resolved to N elements`.
   Note this is a *hard error*, not a silent wrong-element click.
2. **Brittleness.** `.button` and `#search` are styling/implementation details.
   A CSS refactor that renames a class breaks the test even though the user-facing
   behaviour is unchanged. Tests should bind to what the user perceives.

**Fix — target the element by its accessible role and name:**

```python
page.get_by_role("button", name="Search").click()
```

If the application has no accessible name to hang this on, the next-best option
is an explicit, purpose-built hook (`page.get_by_test_id("search-submit")`),
which at least signals to developers that the attribute is load-bearing. Falling
back to CSS, scope it and disambiguate deliberately:
`page.locator("form.search .button").first`.

---

## Bug 6 — Unused Selenium import mixing two incompatible frameworks *(medium)*

```python
from selenium import webdriver
```

`webdriver` is never referenced. The import is dead code, and it is actively
harmful:

* It forces Selenium to be a dependency of the project for no reason — a heavy
  install, plus browser-driver version management that has to be kept in step.
* If Selenium is *not* installed, the module raises `ImportError` at **collection**
  time, so the whole test file fails to load and every test in it is reported as
  an error, not just this one.
* It misleads the next reader into thinking the file drives a Selenium session
  as well, and invites someone to genuinely mix the two drivers later.

**Fix — delete the line.**

```python
from playwright.sync_api import sync_playwright, expect
```

---

## The corrected test

```python
import pytest
from playwright.sync_api import Page, expect


def test_search_returns_results(page: Page) -> None:
    """The browser lifecycle lives in the `page` fixture (see Bugs 2 and 3)."""
    page.goto("https://example.com", wait_until="domcontentloaded")

    page.get_by_role("searchbox").fill("playwright testing")
    page.get_by_role("button", name="Search").click()

    results = page.locator(".result-item")
    expect(results.first).to_be_visible()
    assert results.count() > 0, "The search returned no results"
```

## Issues at a glance

| # | Issue | Severity | Effect |
|---|-------|----------|--------|
| 1 | No assertion — the locator is never resolved | Critical | The test can never fail |
| 2 | `sync_playwright()` never stopped | High | Leaks a Node driver process per run |
| 3 | No `try/finally` around teardown | High | Leaks a browser whenever the test fails |
| 4 | `time.sleep()` instead of auto-waiting | High | Flaky when slow, wasteful when fast |
| 5 | `.button` is ambiguous and brittle | Medium | Strict-mode error; breaks on CSS refactors |
| 6 | Unused Selenium import | Medium | Dead dependency; collection error if absent |
