"""The four business functions required by the exercise.

This is the *flow* (service) layer: it orchestrates page objects and owns no
selectors of its own, which keeps the page objects free of business rules and
the tests free of Playwright.

    authenticate()
    search_items_by_name_under_price(query, max_price, limit=5) -> list[str]
    add_items_to_cart(urls)                                     -> list[AddToCartResult]
    assert_cart_total_not_exceeds(budget_per_item, items_count) -> CartAssertion
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from playwright.sync_api import Page

from src.core.config import Config, get_config
from src.core.logger import get_logger
from src.pages.cart_page import CartPage
from src.pages.home_page import HomePage
from src.pages.item_page import AddToCartResult, ItemPage
from src.pages.login_page import AuthResult, LoginPage
from src.pages.search_results_page import SearchResultItem, SearchResultsPage


class CartTotalExceededError(AssertionError):
    """Raised when the cart subtotal is above budget_per_item * items_count."""


@dataclass
class CartAssertion:
    subtotal: Optional[float]
    threshold: float
    items_count: int
    line_items: int
    screenshot: str = ""
    passed: bool = False


@dataclass
class ShoppingFlow:
    """Facade over the page objects; one instance per browser page."""

    page: Page
    config: Config = field(default_factory=get_config)
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        self.log = get_logger("ShoppingFlow")
        self.home = HomePage(self.page, self.config)
        self.results = SearchResultsPage(self.page, self.config)
        self.item = ItemPage(self.page, self.config, rng=self.rng)
        self.cart = CartPage(self.page, self.config)
        self.login = LoginPage(self.page, self.config)

    # ------------------------------------------------------------------ (1) --
    def authenticate(self) -> AuthResult:
        result = self.login.authenticate()
        self.log.info("Authentication [%s] -> %s (%s)", result.strategy, result.authenticated, result.detail)
        return result

    # ------------------------------------------------------------------ (2) --
    def search_items_by_name_under_price(
        self, query: str, max_price: float, limit: int = 5
    ) -> List[str]:
        """Up to ``limit`` listing URLs whose price is <= ``max_price``.

        Uses the site's own price filter when present, then verifies every price
        client-side. If the current page yields fewer than ``limit`` matches it
        follows "Next" until the quota is met or the pages run out - returning
        whatever was found (an empty list is a valid answer).
        """
        return [item.url for item in self.search_items_detailed(query, max_price, limit)]

    def search_items_detailed(
        self, query: str, max_price: float, limit: int = 5
    ) -> List[SearchResultItem]:
        self.home.open()
        # The site's own price filter is applied here (via the sidebar widget when
        # it renders, otherwise through the `_udhi` URL parameter it submits).
        results = self.home.search(query, max_price)
        results.apply_price_filter(max_price)

        collected: List[SearchResultItem] = []
        seen: set[str] = set()
        pages_scanned = 0
        max_pages = self.config.runtime.max_pages_to_scan

        while len(collected) < limit and pages_scanned < max_pages:
            pages_scanned += 1
            for item in results.collect_items_under_price(max_price, limit - len(collected)):
                if item.url in seen:
                    continue
                seen.add(item.url)
                collected.append(item)
                if len(collected) >= limit:
                    break

            if len(collected) >= limit:
                break
            if not results.go_to_next_page():
                self.log.info("Paging exhausted after %s page(s)", pages_scanned)
                break

        self.log.info(
            "Search %r <= %.2f: %s/%s item(s) over %s page(s)",
            query, max_price, len(collected), limit, pages_scanned,
        )
        results.screenshot(f"search_{query}_{max_price:g}")
        return collected

    # ------------------------------------------------------------------ (3) --
    def add_items_to_cart(self, urls: Sequence[str]) -> List[AddToCartResult]:
        """Open every URL, choose random variants, add to the cart, log + screenshot.

        A listing that cannot be added (auction-only, sold out) is recorded and
        skipped rather than aborting the run; the caller decides what to do.
        """
        outcomes: List[AddToCartResult] = []
        for index, url in enumerate(urls, start=1):
            self.log.info("[%s/%s] Adding to cart: %s", index, len(urls), url)
            self.page.goto(url, wait_until="domcontentloaded")
            self.item.dismiss_consent_banner()
            outcome = self.item.add_to_cart()
            outcomes.append(outcome)
            self.log.info(
                "[%s/%s] %s | price=%s | variants=%s | added=%s %s",
                index, len(urls), outcome.title[:60], outcome.price,
                outcome.variants or "-", outcome.added, outcome.reason,
            )
            # Return to the search context, as the exercise requires.
            self.page.go_back(wait_until="domcontentloaded")
        return outcomes

    # ------------------------------------------------------------------ (4) --
    def assert_cart_total_not_exceeds(self, budget_per_item: float, items_count: int) -> CartAssertion:
        """Assert cart subtotal <= budget_per_item * items_count."""
        self.cart.open_cart()
        threshold = budget_per_item * items_count
        subtotal = self.cart.subtotal()
        line_items = self.cart.line_item_count()
        shot = self.cart.screenshot("cart_total", full_page=True)

        assertion = CartAssertion(
            subtotal=subtotal,
            threshold=threshold,
            items_count=items_count,
            line_items=line_items,
            screenshot=str(shot),
        )

        if subtotal is None:
            raise AssertionError(f"Cart subtotal could not be read (screenshot: {shot})")
        if subtotal > threshold:
            raise CartTotalExceededError(
                f"Cart subtotal {subtotal:.2f} exceeds the budget "
                f"{budget_per_item:.2f} x {items_count} = {threshold:.2f} (screenshot: {shot})"
            )

        assertion.passed = True
        self.log.info("Cart subtotal %.2f <= threshold %.2f - OK", subtotal, threshold)
        return assertion
