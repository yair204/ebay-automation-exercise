"""Creation and teardown of Playwright browser/context/page objects."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from src.core.config import Config
from src.core.logger import get_logger

_LOG = get_logger(__name__)

# A plain automation UA makes eBay serve the bot-challenge page far more often.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class BrowserFactory:
    """Owns the Playwright lifecycle so no page object ever has to."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ------------------------------------------------------------------ setup
    def start(self) -> Page:
        cfg = self._config.browser
        _LOG.info("Launching %s (headless=%s, profile=%s)", cfg.name, cfg.headless, self._config.profile)

        self._playwright = sync_playwright().start()
        launcher = getattr(self._playwright, cfg.name)
        self._browser = launcher.launch(headless=cfg.headless, slow_mo=cfg.slow_mo_ms)
        self._context = self._browser.new_context(
            viewport={"width": cfg.viewport.width, "height": cfg.viewport.height},
            user_agent=_USER_AGENT,
            locale=self._config.app.locale,
        )
        self._context.set_default_timeout(cfg.default_timeout_ms)
        self._context.set_default_navigation_timeout(cfg.navigation_timeout_ms)

        if self._config.reporting.record_trace:
            self._context.tracing.start(screenshots=True, snapshots=True, sources=True)

        return self._context.new_page()

    # --------------------------------------------------------------- teardown
    def stop(self, trace_name: str = "trace") -> None:
        if self._context is not None:
            if self._config.reporting.record_trace:
                trace_path: Path = self._config.traces_path() / f"{trace_name}.zip"
                try:
                    self._context.tracing.stop(path=str(trace_path))
                    _LOG.info("Trace saved: %s", trace_path)
                except Exception as exc:  # pragma: no cover - best effort
                    _LOG.warning("Could not save trace: %s", exc)
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._context = None

    @property
    def context(self) -> BrowserContext | None:
        return self._context


@contextmanager
def browser_page(config: Config, trace_name: str = "trace") -> Iterator[Page]:
    factory = BrowserFactory(config)
    page = factory.start()
    try:
        yield page
    finally:
        factory.stop(trace_name)
