"""Search results page: price filtering, price-aware item extraction and paging."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote_plus, urlparse, urlunparse

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError

from src.core.base_page import BasePage
from src.core.price_parser import PriceParser


@dataclass(frozen=True)
class SearchResultItem:
    """One qualifying listing: the value object the search function returns."""

    url: str
    title: str
    price: float

    def __str__(self) -> str:  # pragma: no cover - logging sugar
        return f"{self.price:>8.2f} | {self.title[:60]}"


class SearchResultsPage(BasePage):
    URL_PATH = "/sch/i.html"

    # --- Item cards. XPath as required by the exercise, with CSS fallbacks that
    #     cover eBay's newer "brw" grid layout.
    _ITEM_CARDS_XPATH = (
        "xpath=//li[contains(@class,'s-item') or contains(@class,'s-card')]"
        "[.//a[contains(@href,'/itm/')]]"
    )
    _ITEM_CARDS_CSS = "li.s-item, li.s-card, li[data-viewport]"

    _CARD_LINK_XPATH = ".//a[contains(@href,'/itm/')]"
    _CARD_TITLE_XPATH = (
        ".//div[contains(@class,'s-item__title') or contains(@class,'s-card__title')]"
        " | .//span[@role='heading']"
    )
    _CARD_PRICE_XPATH = (
        ".//span[contains(@class,'s-item__price') or contains(@class,'s-card__price')]"
    )

    # --- Sidebar price filter
    # NOTE: the aria-labels are localised ("Minimum Value in ILS", "Maximum value US $"),
    # so they are matched case-insensitively by prefix rather than by an exact string.
    _PRICE_MIN = (
        "input[name='_udlo']",
        "input[aria-label^='Minimum Value' i]",
        "#price-graph-knob-min",
    )
    _PRICE_MAX = (
        "input[name='_udhi']",
        "input[aria-label^='Maximum value' i]",
        "#price-graph-knob-max",
    )
    _PRICE_SUBMIT = (
        "button[aria-label='Submit price range']",
        "button:has-text('Apply')",
        "input[type='submit'][value='Go']",
    )

    _NEXT_PAGE = (
        "a.pagination__next[href]",
        "a[aria-label='Go to next search page'][href]",
        "a[type='next'][href]",
    )
    _NO_RESULTS = "text=/No exact matches found|0 results for/i"

    # eBay injects a placeholder promo card as the first result on every SRP.
    # It has a valid /itm/ href and a price, so it must be filtered out by title.
    _PLACEHOLDER_TITLES = ("shop on ebay",)

    # ------------------------------------------------------------ navigation
    def open_query(self, query: str, max_price: Optional[float] = None) -> "SearchResultsPage":
        """Search straight through the results URL, applying eBay's own ``_udhi`` price filter.

        This is the primary path: eBay serves an error page to a fair share of
        automated requests to ``/``, and the SRP URL is both faster and the same
        filter the sidebar widget submits.
        """
        url = f"{self.URL_PATH}?_nkw={quote_plus(query)}&_sacat=0"
        if max_price is not None:
            url += f"&_udhi={max_price:g}"
        self.open(url)
        self.wait_until_loaded()
        return self

    def wait_until_loaded(self) -> None:
        self.dismiss_consent_banner()
        try:
            self.page.locator(self._ITEM_CARDS_XPATH).first.wait_for(state="attached", timeout=15000)
        except PlaywrightTimeoutError:
            self.log.warning("No result cards became visible on %s", self.page.url)

    # -------------------------------------------------------- price filter --
    def apply_price_filter(self, max_price: float, min_price: float = 0.0) -> bool:
        """Use the on-page min/max price filter when it exists.

        Returns ``True`` when the filter was applied through the UI. When the
        sidebar filter is absent the caller keeps the client-side price check as
        the source of truth, so a ``False`` here is not an error.
        """
        if f"_udhi={max_price:g}" in self.page.url:
            self.log.info("Price filter already applied through the URL (_udhi=%g)", max_price)
            return True

        max_input = self.first_visible(self._PRICE_MAX, timeout_ms=3000)
        if max_input is None:
            self.log.info("No on-page price filter - relying on the URL/_udhi filter and client-side checks")
            return False

        min_input = self.first_visible(self._PRICE_MIN, timeout_ms=1500)
        if min_input is not None and min_price:
            min_input.fill(f"{min_price:g}")
        max_input.fill(f"{max_price:g}")

        submit = self.first_visible(self._PRICE_SUBMIT, timeout_ms=2000)
        if submit is not None:
            submit.click()
        else:
            max_input.press("Enter")

        self.wait_until_loaded()
        self.log.info("Applied price filter: max=%s", max_price)
        return True

    # ------------------------------------------------------------ scraping --
    def collect_items_under_price(self, max_price: float, limit: int) -> List[SearchResultItem]:
        """Items on the *current* page whose price is <= ``max_price`` (up to ``limit``)."""
        cards = self.page.locator(self._ITEM_CARDS_XPATH)
        count = cards.count()
        if count == 0:
            cards = self.page.locator(self._ITEM_CARDS_CSS)
            count = cards.count()

        self.log.info("Scanning %s cards on %s", count, self.page.url)
        found: List[SearchResultItem] = []
        seen: set[str] = set()

        for index in range(count):
            if len(found) >= limit:
                break
            item = self._parse_card(cards.nth(index))
            if item is None or item.price > max_price or item.url in seen:
                continue
            seen.add(item.url)
            found.append(item)
            self.log.info("  match %s", item)

        return found

    def _parse_card(self, card: Locator) -> Optional[SearchResultItem]:
        try:
            link = card.locator(f"xpath={self._CARD_LINK_XPATH}").first
            href = link.get_attribute("href", timeout=2000)
        except PlaywrightTimeoutError:
            return None
        if not href or "/itm/" not in href:
            return None

        price_text = self.safe_text(card.locator(f"xpath={self._CARD_PRICE_XPATH}").first)
        price = PriceParser.parse(price_text)
        if price is None:
            return None

        title = self.safe_text(card.locator(f"xpath={self._CARD_TITLE_XPATH}").first, default="(no title)")
        if title.strip().lower() in self._PLACEHOLDER_TITLES:
            return None

        return SearchResultItem(url=self._canonical(href), title=title, price=price)

    @staticmethod
    def _canonical(href: str) -> str:
        """Strip tracking query/fragment so the same listing is never counted twice."""
        parsed = urlparse(href)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    # -------------------------------------------------------------- paging --
    def has_next_page(self) -> bool:
        return self.first_visible(self._NEXT_PAGE, timeout_ms=2500) is not None

    def go_to_next_page(self) -> bool:
        next_link = self.first_visible(self._NEXT_PAGE, timeout_ms=2500)
        if next_link is None:
            self.log.info("No further pages available")
            return False
        self.scroll_into_view(next_link)
        self.log.info("Moving to the next results page")
        next_link.click()
        self.wait_until_loaded()
        return True

    def has_results(self) -> bool:
        return not self.exists(self._NO_RESULTS, timeout_ms=1500)
