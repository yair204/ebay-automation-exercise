"""eBay landing page - the entry point of every scenario."""
from __future__ import annotations

from typing import Optional

from src.core.base_page import BasePage, xp_has_text
from src.pages.search_results_page import SearchResultsPage


class HomePage(BasePage):
    URL_PATH = "/"

    _SEARCH_INPUT = (
        "xpath=//input[@id='gh-ac']",
        "xpath=//input[@name='_nkw']",
        f"xpath=//input[{xp_has_text('search for anything', '@aria-label')}]",
    )
    _SEARCH_BUTTON = (
        "xpath=//*[@id='gh-search-btn' or @id='gh-btn']",
        "xpath=//input[@type='submit' and @value='Search']",
    )
    _ERROR_PAGE = (
        f"xpath=//*[self::h1 or self::h2]"
        f"[{xp_has_text('error page')} or {xp_has_text('something went wrong')}]"
    )

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
