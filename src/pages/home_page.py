"""eBay landing page - the entry point of every scenario."""
from __future__ import annotations

from typing import Optional

from src.core.base_page import BasePage
from src.pages.search_results_page import SearchResultsPage


class HomePage(BasePage):
    URL_PATH = "/"

    _SEARCH_INPUT = (
        "input#gh-ac",
        "input[name='_nkw']",
        "input[aria-label='Search for anything']",
    )
    _SEARCH_BUTTON = (
        "#gh-search-btn",
        "#gh-btn",
        "input[type='submit'][value='Search']",
    )
    _ERROR_PAGE = "text=/Error Page|something went wrong/i"

    def search(self, query: str, max_price: Optional[float] = None) -> SearchResultsPage:
        """Search for ``query``, preferring the header search box.

        eBay serves an error page to a noticeable share of automated requests to
        ``/``. Rather than burning the full timeout on three selectors that will
        never resolve there, the header is probed briefly and the run falls back
        to the results URL - which is also where eBay's own ``_udhi`` price
        filter is applied.
        """
        self.log.info("Searching for %r", query)
        results = SearchResultsPage(self.page, self.config)

        if self.exists(self._ERROR_PAGE, timeout_ms=800):
            self.log.warning("Home page returned an error page - using the search URL")
            return results.open_query(query, max_price)

        search_box = self.first_visible(self._SEARCH_INPUT, timeout_ms=2500)
        if search_box is None:
            self.log.warning("Header search box not available - using the search URL")
            return results.open_query(query, max_price)

        search_box.fill(query)
        button = self.first_visible(self._SEARCH_BUTTON, timeout_ms=1500)
        if button is not None:
            button.click()
        else:
            search_box.press("Enter")

        results.wait_until_loaded()
        return results
