"""Common behaviour shared by every page object (POM base class)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from src.core.config import Config, get_config
from src.core.logger import get_logger

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class BotChallengeError(RuntimeError):
    """eBay served its "Security Measure" interstitial instead of the page.

    Raised as a distinct type so a blocked run is never mistaken for a product
    bug. Solving the captcha is deliberately out of scope - see README.
    """


class BasePage:
    """Thin, opinionated wrapper over ``Page``.

    Responsibilities kept here (and nowhere else):
      * navigation + waiting helpers
      * resilient "first locator that exists" resolution
      * screenshot / artifact naming
      * cookie & interstitial dismissal
    Page-specific selectors and business actions live in the subclasses.
    """

    # Overridden by subclasses that have a canonical URL fragment.
    URL_PATH: str = "/"

    # eBay redirects to /splashui/captcha when it decides a session is automated.
    _CHALLENGE_URL_MARKER = "/splashui/captcha"
    _CHALLENGE_TEXT = "text=/Please verify yourself|Security Measure/i"

    _CONSENT_SELECTORS: Sequence[str] = (
        "#gdpr-banner-accept",
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "[aria-label='Accept all cookies']",
    )

    def __init__(self, page: Page, config: Optional[Config] = None) -> None:
        self.page = page
        self.config = config or get_config()
        self.log = get_logger(type(self).__name__)

    # ---------------------------------------------------------- navigation --
    def open(self, path: str | None = None) -> "BasePage":
        url = self._absolute(path if path is not None else self.URL_PATH)
        self.log.info("Navigating to %s", url)
        self.page.goto(url, wait_until="domcontentloaded")
        self.dismiss_consent_banner()
        return self

    def is_bot_challenge(self) -> bool:
        return self._CHALLENGE_URL_MARKER in self.page.url or self.exists(self._CHALLENGE_TEXT, timeout_ms=1500)

    def raise_if_bot_challenge(self, context: str) -> None:
        """Fail loudly and diagnosably when eBay blocks the session."""
        if not self.is_bot_challenge():
            return
        shot = self.screenshot(f"bot_challenge_{context}")
        raise BotChallengeError(
            f"eBay served its bot-verification page while {context}. "
            f"The run cannot continue; solving the captcha is out of scope. "
            f"Screenshot: {shot}"
        )

    _ABSOLUTE_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

    def _absolute(self, path: str) -> str:
        """Join ``path`` onto the base URL unless it already carries a scheme.

        Any scheme counts, not just http(s) - local ``file://`` fixtures are used
        to exercise the cart logic offline.
        """
        if self._ABSOLUTE_URL.match(path):
            return path
        return f"{self.config.app.base_url.rstrip('/')}/{path.lstrip('/')}"

    def wait_for_idle(self, timeout_ms: int = 8000) -> None:
        """Best-effort settle. eBay keeps long-polling, so a timeout is not a failure."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            self.log.debug("networkidle not reached within %sms - continuing", timeout_ms)

    # ------------------------------------------------------------ locators --
    def first_visible(self, selectors: Iterable[str], timeout_ms: int = 4000) -> Optional[Locator]:
        """Return the first selector in ``selectors`` that resolves to a visible element.

        eBay serves several A/B layouts; instead of one brittle selector each page
        object declares a *ranked list* and this helper picks whichever is live.
        """
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except PlaywrightTimeoutError:
                continue
        return None

    def exists(self, selector: str, timeout_ms: int = 2000) -> bool:
        try:
            self.page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except PlaywrightTimeoutError:
            return False

    def safe_text(self, locator: Locator, default: str = "") -> str:
        try:
            return (locator.inner_text(timeout=3000) or "").strip()
        except PlaywrightTimeoutError:
            return default

    # ------------------------------------------------------------- actions --
    def dismiss_consent_banner(self) -> None:
        banner = self.first_visible(self._CONSENT_SELECTORS, timeout_ms=1500)
        if banner is not None:
            self.log.info("Dismissing consent banner")
            try:
                banner.click()
            except PlaywrightTimeoutError:
                pass

    def scroll_into_view(self, locator: Locator) -> None:
        try:
            locator.scroll_into_view_if_needed(timeout=3000)
        except PlaywrightTimeoutError:
            pass

    # ----------------------------------------------------------- artifacts --
    def screenshot(self, name: str, full_page: bool = False) -> Path:
        stamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        filename = f"{_SAFE_NAME.sub('_', name)}_{stamp}.png"
        path = self.config.screenshots_path() / filename
        self.page.screenshot(path=str(path), full_page=full_page)
        self.log.info("Screenshot saved: %s", path)
        self._attach_to_allure(path, name)
        return path

    @staticmethod
    def _attach_to_allure(path: Path, name: str) -> None:
        try:
            import allure

            allure.attach.file(str(path), name=name, attachment_type=allure.attachment_type.PNG)
        except Exception:  # allure not installed / not running under allure
            pass
