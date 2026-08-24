"""Deterministic verification of function (4), assert_cart_total_not_exceeds.

The live cart (cart.ebay.com) is behind eBay's bot verification, so the E2E run
cannot always reach it. These tests drive the *real* CartPage and ShoppingFlow
against a local replica of eBay's cart markup, so the price-reading and
budget-assertion logic is proven independently of the site's availability.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.browser_factory import BrowserFactory
from src.core.config import get_config
from src.flows.shopping_flow import CartTotalExceededError, ShoppingFlow

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def offline_flow():
    config = get_config()
    factory = BrowserFactory(config)
    page = factory.start()
    try:
        yield ShoppingFlow(page=page, config=config)
    finally:
        factory.stop(trace_name="offline_cart")


def _point_cart_at(flow: ShoppingFlow, fixture: str) -> None:
    """Serve the fixture as the cart URL, leaving all cart logic untouched."""
    flow.cart.URL_PATH = (FIXTURES / fixture).as_uri()


@pytest.mark.unit
def test_reads_subtotal_and_passes_within_budget(offline_flow: ShoppingFlow):
    _point_cart_at(offline_flow, "cart.html")

    result = offline_flow.assert_cart_total_not_exceeds(budget_per_item=10.0, items_count=3)

    assert result.subtotal == 20.98
    assert result.threshold == 30.0
    assert result.line_items == 3
    assert result.passed


@pytest.mark.unit
def test_raises_when_the_cart_exceeds_the_budget(offline_flow: ShoppingFlow):
    _point_cart_at(offline_flow, "cart_over_budget.html")

    with pytest.raises(CartTotalExceededError) as excinfo:
        offline_flow.assert_cart_total_not_exceeds(budget_per_item=220.0, items_count=1)

    assert "1299.00" in str(excinfo.value)


@pytest.mark.unit
def test_threshold_scales_with_the_item_count(offline_flow: ShoppingFlow):
    _point_cart_at(offline_flow, "cart_over_budget.html")

    # 1299 <= 220 * 6, so the same cart passes once the count is high enough.
    result = offline_flow.assert_cart_total_not_exceeds(budget_per_item=220.0, items_count=6)
    assert result.passed and result.threshold == 1320.0
