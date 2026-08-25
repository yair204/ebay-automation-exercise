"""Single listing page: random variant selection and "Add to cart"."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError

from src.core.base_page import BasePage, xp_deepest_with_text, xp_has_class, xp_has_text
from src.core.price_parser import PriceParser


@dataclass
class AddToCartResult:
    url: str
    title: str
    price: Optional[float]
    variants: Dict[str, str]
    added: bool
    reason: str = ""


class ItemPage(BasePage):
    _TITLE = (
        f"xpath=//h1[{xp_has_class('x-item-title__mainTitle')}]//span[normalize-space()]",
        "xpath=//h1[@itemprop='name']",
        f"xpath=//h1[{xp_has_class('x-item-title__mainTitle')}]",
        "xpath=//h1[normalize-space()]",
    )
    _PRICE = (
        f"xpath=//div[@data-testid='x-price-primary']//span[{xp_has_class('ux-textspans')}]",
        "xpath=//span[@itemprop='price']",
        "xpath=//*[@id='prcIsum' or @id='mm-saleDscPrc']",
        f"xpath=//*[{xp_has_class('x-price-primary')}]//span[normalize-space()]",
    )
    # The item page renders BOTH "Buy It Now" and "Add to cart" as
    # a[data-testid='ux-call-to-action'], so the id / text is what disambiguates
    # them - matching on data-testid alone would click "Buy It Now".
    _ADD_TO_CART = (
        "xpath=//a[@id='atcBtn_btn_1']",
        "xpath=//a[starts-with(@id, 'atcBtn_btn')]",
        # Both CTAs share data-testid='ux-call-to-action'; only the text tells
        # "Add to cart" apart from "Buy It Now", so the predicate is essential.
        f"xpath=//a[@data-testid='ux-call-to-action'][{xp_has_text('add to cart')}]",
        "xpath=//a[@id='atcRedesignId_btn']",
        f"xpath=//button[{xp_has_text('add to cart')}]",
    )
    # Scoped to the variant widget: an unscoped `select` would also match the
    # header's category dropdown (#gh-cat) and silently change the search scope.
    _VARIANT_SELECTS = (
        f"xpath=//*[{xp_has_class('x-msku')} or {xp_has_class('x-msku-evo')}]"
        f"//select[{xp_has_class('listbox__native')}]"
        f" | //select[starts-with(@name, 'msku')]"
    )
    _VARIANT_BUTTONS = (
        f"xpath=//*[{xp_has_class('x-msku-evo')} or {xp_has_class('x-msku')}]"
        f"//button[@aria-expanded][{xp_has_class('listbox-button__control')}]"
        f" | //div[@data-testid='x-msku']//button[@aria-expanded]"
    )
    # Every group's options live in the DOM at once, so a match must be filtered
    # down to the *open* listbox. XPath 1.0 cannot express visibility, so unlike
    # the CSS `:visible` pseudo-class this is filtered in code - see
    # `_pick_random_option`, which skips anything not actually rendered.
    _VARIANT_OPTIONS = (
        f"xpath=//*[@role='option'] | //*[{xp_has_class('listbox__option')}]"
    )
    _VARIANT_ERROR = (
        f"xpath={xp_deepest_with_text('please select')}"
        f" | {xp_deepest_with_text('select a valid')}",
        f"xpath=//*[@role='alert'][{xp_has_text('select')}]",
    )
    _ADDED_CONFIRMATION = (
        f"xpath={xp_deepest_with_text('added to cart')}",
        f"xpath=//h1[{xp_has_text('shopping cart')}]",
        "xpath=//*[@data-test-id='cart-line-item' or @data-testid='cart-line-item']",
    )

    def __init__(self, page, config=None, rng: Optional[random.Random] = None) -> None:
        super().__init__(page, config)
        # Injected RNG => variant choices are reproducible when a seed is given.
        self._rng = rng or random.Random()

    # ------------------------------------------------------------- reading --
    def title(self) -> str:
        locator = self.first_visible(self._TITLE, timeout_ms=8000)
        return self.safe_text(locator, default="(unknown item)") if locator else "(unknown item)"

    def price(self) -> Optional[float]:
        locator = self.first_visible(self._PRICE, timeout_ms=6000)
        return PriceParser.parse(self.safe_text(locator)) if locator else None

    # ------------------------------------------------------------ variants --
    def select_random_variants(self) -> Dict[str, str]:
        """Pick a random *available* value for every variant control on the page.

        eBay's variant widget is a custom listbox: the ``<select>`` in the DOM is
        a hidden shell whose options carry index values and no text, so it cannot
        be driven with ``select_option``. The visible control is a
        ``button.listbox-button__control`` that expands a ``[role=option]`` list -
        that is what this method drives, falling back to the native select.
        """
        chosen = self._select_listbox_groups()
        if not chosen:
            chosen = self._select_native_dropdowns()
        if chosen:
            self.log.info("Selected variants: %s", chosen)
        return chosen

    def _select_listbox_groups(self) -> Dict[str, str]:
        """Fill every variant group, re-scanning after each pick.

        Choosing a value re-renders the whole widget (eBay re-computes which
        combinations are still in stock), which invalidates the other buttons.
        So instead of one pass over a stale list, this keeps re-scanning for a
        group that still reads "Select" until none are left.
        """
        chosen: Dict[str, str] = {}
        group_count = self.page.locator(self._VARIANT_BUTTONS).count()

        # At most one pass per group, plus a small margin for re-renders.
        for _ in range(group_count * 2):
            index = self._first_unselected_group()
            if index is None:
                break

            button = self.page.locator(self._VARIANT_BUTTONS).nth(index)
            label = self.safe_text(button).split("\n")[0].strip().rstrip(":") or f"group_{index}"
            try:
                self.scroll_into_view(button)
                button.click(timeout=4000)
            except PlaywrightTimeoutError:
                break

            value = self._pick_random_option()
            if not value:
                self.page.keyboard.press("Escape")
                continue
            chosen[label] = value
            self.wait_for_idle(3000)

        if len(chosen) < group_count:
            self.log.warning("Only %s/%s variant group(s) could be set", len(chosen), group_count)
        return chosen

    def _first_unselected_group(self) -> Optional[int]:
        """Index of the first variant button still showing the "Select" placeholder."""
        buttons = self.page.locator(self._VARIANT_BUTTONS)
        for index in range(buttons.count()):
            text = self.safe_text(buttons.nth(index)).lower()
            if "select" in text.split("\n")[-1] or text.rstrip().endswith("select"):
                return index
        return None

    def _pick_random_option(self) -> Optional[str]:
        """Click a random selectable entry in the currently expanded listbox."""
        options = self.page.locator(self._VARIANT_OPTIONS)
        try:
            # Wait on the visible subset: `options.first` is the *closed* group's
            # hidden entry, which would never become visible.
            self.page.locator(f"{self._VARIANT_OPTIONS} >> visible=true").first.wait_for(
                state="visible", timeout=4000
            )
        except PlaywrightTimeoutError:
            return None

        candidates: List[int] = []
        for index in range(options.count()):
            option = options.nth(index)
            if not option.is_visible():
                continue
            text = self.safe_text(option).lower()
            disabled = option.get_attribute("aria-disabled") == "true"
            # Skip the placeholder and anything unavailable.
            if disabled or not text or text.startswith("select") or "out of stock" in text:
                continue
            candidates.append(index)

        if not candidates:
            return None

        pick = options.nth(self._rng.choice(candidates))
        label = self.safe_text(pick).split("\n")[0]
        try:
            pick.click(timeout=4000)
        except PlaywrightTimeoutError:
            return None
        return label

    def _select_native_dropdowns(self) -> Dict[str, str]:
        """Fallback for listings that still render plain ``<select>`` variants."""
        chosen: Dict[str, str] = {}
        selects = self.page.locator(self._VARIANT_SELECTS)
        for index in range(selects.count()):
            select = selects.nth(index)
            try:
                options = select.locator("option")
                values: List[str] = []
                for opt_index in range(options.count()):
                    option = options.nth(opt_index)
                    value = option.get_attribute("value") or ""
                    label = (option.inner_text() or "").strip().lower()
                    disabled = option.get_attribute("disabled") is not None
                    # "-1"/"" are eBay's placeholder values.
                    if not value or value == "-1" or disabled:
                        continue
                    if label.startswith("select") or "out of stock" in label:
                        continue
                    values.append(value)
                if not values:
                    continue
                pick = self._rng.choice(values)
                select.select_option(pick, timeout=4000)
                chosen[select.get_attribute("name") or f"select_{index}"] = pick
                self.wait_for_idle(3000)
            except PlaywrightTimeoutError:
                continue
            except Exception as exc:  # hidden shell select - not selectable
                self.log.debug("Native select %s not selectable: %s", index, exc)
                continue
        return chosen

    def set_quantity(self, quantity: int) -> None:
        box: Optional[Locator] = self.first_visible(
            ("xpath=//input[@id='qtyTextBox']", "xpath=//input[@name='quantity']"), timeout_ms=2000
        )
        if box is not None:
            box.fill(str(quantity))

    # ---------------------------------------------------------- add to cart --
    def add_to_cart(self) -> AddToCartResult:
        title, price = self.title(), self.price()
        variants = self.select_random_variants()

        button = self.first_visible(self._ADD_TO_CART, timeout_ms=8000)
        if button is None:
            self.log.warning("No 'Add to cart' control on %s (likely auction-only)", self.page.url)
            self.screenshot(f"no_atc_{title[:30]}")
            return AddToCartResult(self.page.url, title, price, variants, False, "Add to cart button not found")

        self.scroll_into_view(button)
        button.click()
        self.wait_for_idle(6000)

        added = self.first_visible(self._ADDED_CONFIRMATION, timeout_ms=6000) is not None
        self.screenshot(f"added_{title[:30]}" if added else f"atc_unconfirmed_{title[:30]}")
        if not added:
            self.log.warning("Add-to-cart confirmation not detected for %r", title)
        return AddToCartResult(
            self.page.url, title, price, variants, added, "" if added else "confirmation not detected"
        )
