"""Shopping cart page: reads the subtotal that the site itself displays."""
from __future__ import annotations

from typing import Optional

from src.core.base_page import BasePage, xp_deepest_with_text, xp_has_text
from src.core.price_parser import PriceParser


class CartPage(BasePage):
    URL_PATH = "https://cart.ebay.com/"

    _SUBTOTAL = (
        "xpath=//*[@data-test-id='SUBTOTAL']"
        "//span[contains(concat(' ', normalize-space(@class), ' '), ' text-display-span ')]",
        "xpath=//*[@data-test-id='SUBTOTAL']",
        "xpath=//*[@data-test-id='cart-subtotal']",
        # Structural fallback: find the "Subtotal" label and walk the `following`
        # axis to the next element that actually holds a value. This is the case
        # XPath handles and CSS cannot express at all.
        f"xpath=//span[{xp_has_text('subtotal')}]/following::span[normalize-space()][1]",
    )
    _TOTAL = (
        "xpath=//*[@data-test-id='TOTAL']",
        "xpath=//*[@data-test-id='ORDER_TOTAL']",
    )
    _LINE_ITEMS = (
        "xpath=//*[@data-test-id='cart-line-item']"
        " | //*[contains(concat(' ', normalize-space(@class), ' '), ' cart-bucket ')]"
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' item-card ')]"
    )
    _EMPTY = f"xpath={xp_deepest_with_text('your cart is empty')}"

    def open_cart(self) -> "CartPage":
        self.open(self.URL_PATH)
        self.wait_for_idle(8000)
        self.raise_if_bot_challenge("opening the shopping cart")
        return self

    def is_empty(self) -> bool:
        return self.exists(self._EMPTY, timeout_ms=3000)

    def line_item_count(self) -> int:
        return self.page.locator(self._LINE_ITEMS).count()

    def subtotal(self) -> Optional[float]:
        """The cart subtotal as printed by eBay, falling back to the order total."""
        for selectors in (self._SUBTOTAL, self._TOTAL):
            locator = self.first_visible(selectors, timeout_ms=5000)
            if locator is None:
                continue
            value = PriceParser.parse(self.safe_text(locator))
            if value is not None:
                self.log.info("Cart amount read from the page: %.2f", value)
                return value
        self.log.warning("Could not read the cart subtotal")
        return None
