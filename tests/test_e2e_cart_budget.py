"""End-to-end scenario, driven entirely by data/test_data.json."""
from __future__ import annotations

import pytest

from src.core.base_page import BotChallengeError
from src.flows.shopping_flow import ShoppingFlow


@pytest.mark.e2e
class TestCartBudget:
    """search -> add to cart -> assert the total stays within budget."""

    def test_cart_total_stays_within_budget(self, flow: ShoppingFlow, scenario: dict) -> None:
        query = scenario["query"]
        max_price = float(scenario["max_price"])
        limit = int(scenario["limit"])
        budget_per_item = float(scenario["budget_per_item"])

        # (1) Authentication - guest by default, real credentials when configured.
        auth = flow.authenticate()
        assert auth.authenticated, f"Authentication failed: {auth.detail}"

        # (2) Search with a price condition.
        items = flow.search_items_detailed(query, max_price, limit)
        assert len(items) <= limit, "The search returned more items than requested"
        for item in items:
            assert item.price <= max_price, f"{item.url} costs {item.price} > {max_price}"

        if not items:
            pytest.skip(f"No listing under {max_price} for {query!r} - nothing to add to the cart")

        urls = [item.url for item in items]

        # (3) Add every item to the cart.
        outcomes = flow.add_items_to_cart(urls)
        added = [o for o in outcomes if o.added]
        assert added, "Not a single item could be added to the cart"

        # (4) Assert the cart total against the budget.
        #
        # eBay guards cart.ebay.com with a bot-verification interstitial that this
        # suite deliberately does not try to solve. That is an environment block,
        # not a product defect, so it is reported as a skip - the assertion logic
        # itself is covered deterministically in test_cart_assertion_offline.py.
        try:
            assertion = flow.assert_cart_total_not_exceeds(budget_per_item, len(added))
        except BotChallengeError as exc:
            pytest.skip(str(exc))

        assert assertion.passed
        assert assertion.subtotal is not None and assertion.subtotal <= assertion.threshold

    @pytest.mark.smoke
    def test_search_respects_the_limit_and_price(self, flow: ShoppingFlow, scenario: dict) -> None:
        """Search-only check - fast feedback that does not touch the cart."""
        urls = flow.search_items_by_name_under_price(
            scenario["query"], float(scenario["max_price"]), int(scenario["limit"])
        )
        assert len(urls) <= int(scenario["limit"])
        assert len(set(urls)) == len(urls), "The search returned duplicate listings"
