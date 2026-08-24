"""Shopping cart page: reads the subtotal that the site itself displays."""
from __future__ import annotations

from typing import Optional

from src.core.base_page import BasePage
from src.core.price_parser import PriceParser


class CartPage(BasePage):
    URL_PATH = "https://cart.ebay.com/"

    _SUBTOTAL = (
        "[data-test-id='SUBTOTAL'] span.text-display-span",
        "[data-test-id='SUBTOTAL']",
        "span:has-text('Subtotal') >> xpath=following::span[1]",
        "[data-test-id='cart-subtotal']",
        "text=/Subtotal \\(\\d+ items?\\)/",
    )
    _TOTAL = ("[data-test-id='TOTAL']", "[data-test-id='ORDER_TOTAL']")
    _LINE_ITEMS = "[data-test-id='cart-line-item'], .cart-bucket .item-card"
    _EMPTY = "text=/Your shopping cart is empty|Your cart is empty/i"

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
