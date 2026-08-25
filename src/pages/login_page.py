"""Authentication.

eBay guards its sign-in form with a bot challenge, so the default strategy is a
*guest* session: the flow verifies that an anonymous session is usable (the cart
survives navigation) instead of signing in. Set ``AUTH_STRATEGY=credentials``
to exercise the real form - see README -> Assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.core.base_page import BasePage, xp_deepest_with_text, xp_has_text


@dataclass(frozen=True)
class AuthResult:
    strategy: str
    authenticated: bool
    detail: str = ""


class LoginPage(BasePage):
    URL_PATH = "https://www.ebay.com/signin/"

    _USERNAME = ("xpath=//input[@id='userid']", "xpath=//input[@name='userid']")
    _PASSWORD = ("xpath=//input[@id='pass']", "xpath=//input[@name='pass']")
    _CONTINUE = (
        "xpath=//button[@id='signin-continue-btn']",
        "xpath=//button[@type='submit']",
    )
    _SIGNIN_SUBMIT = ("xpath=//button[@id='sgnBt']", "xpath=//button[@type='submit']")
    _SIGNED_IN_MARKER = (
        "xpath=//*[@id='gh-ug']",
        "xpath=//a[contains(@href, 'myebay')]",
        f"xpath=//*[starts-with(normalize-space(), 'Hi ')][not(.//*[starts-with(normalize-space(), 'Hi ')])]",
    )
    _CHALLENGE = (
        f"xpath={xp_deepest_with_text('verify yourself')}"
        f" | {xp_deepest_with_text('unusual activity')}",
        f"xpath=//iframe[{xp_has_text('challenge', '@title')}]",
    )

    # ------------------------------------------------------------------ API
    def authenticate(self) -> AuthResult:
        strategy = self.config.auth.strategy.lower()
        if strategy == "credentials" and self.config.auth.username:
            return self._sign_in()
        return self._guest_session()

    # ------------------------------------------------------------ strategies
    def _guest_session(self) -> AuthResult:
        self.log.info("Using a guest session (AUTH_STRATEGY=guest)")
        self.open(self.config.app.base_url)
        ok = self.page.title() != ""
        return AuthResult("guest", ok, "anonymous session established")

    def _sign_in(self) -> AuthResult:
        self.log.info("Signing in as %s", self.config.auth.username)
        self.open(self.URL_PATH)

        user = self.first_visible(self._USERNAME, timeout_ms=10000)
        if user is None:
            return AuthResult("credentials", False, "sign-in form not reachable")
        user.fill(self.config.auth.username)

        cont = self.first_visible(self._CONTINUE, timeout_ms=4000)
        if cont is not None:
            cont.click()

        password = self.first_visible(self._PASSWORD, timeout_ms=10000)
        if password is None:
            self.screenshot("login_no_password_field")
            return AuthResult("credentials", False, "password field not reachable (bot challenge?)")
        password.fill(self.config.auth.password)

        submit = self.first_visible(self._SIGNIN_SUBMIT, timeout_ms=4000)
        if submit is not None:
            submit.click()
        self.wait_for_idle(8000)

        if self.first_visible(self._CHALLENGE, timeout_ms=3000) is not None:
            self.screenshot("login_bot_challenge")
            return AuthResult("credentials", False, "bot challenge presented")

        signed_in = self.first_visible(self._SIGNED_IN_MARKER, timeout_ms=6000) is not None
        self.screenshot("login_result")
        return AuthResult("credentials", signed_in, "signed in" if signed_in else "sign-in not confirmed")
