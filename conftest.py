"""Shared pytest fixtures: configuration, browser lifecycle and the flow facade."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
from playwright.sync_api import Page

from src.core.browser_factory import BrowserFactory
from src.core.config import ROOT, Config, get_config
from src.core.logger import get_logger
from src.flows.shopping_flow import ShoppingFlow

_LOG = get_logger("conftest")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--seed", action="store", default=None, help="Seed the RNG used for variant selection")
    parser.addoption(
        "--data-file",
        action="store",
        default="data/test_data.json",
        help="Data-Driven input file (relative to the repo root)",
    )


# --------------------------------------------------------------------- data --
def _load_scenarios(data_file: str) -> List[Dict[str, Any]]:
    path = ROOT / data_file
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)["scenarios"]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Data-Driven: parametrize any test that asks for a ``scenario`` fixture."""
    if "scenario" not in metafunc.fixturenames:
        return
    scenarios = _load_scenarios(metafunc.config.getoption("--data-file"))
    metafunc.parametrize("scenario", scenarios, ids=[s["id"] for s in scenarios])


# ------------------------------------------------------------------ fixtures --
@pytest.fixture(scope="session")
def config() -> Config:
    cfg = get_config()
    _LOG.info("Profile=%s | base_url=%s | browser=%s | headless=%s",
              cfg.profile, cfg.app.base_url, cfg.browser.name, cfg.browser.headless)
    return cfg


@pytest.fixture()
def rng(request: pytest.FixtureRequest) -> random.Random:
    seed = request.config.getoption("--seed")
    return random.Random(int(seed)) if seed is not None else random.Random()


@pytest.fixture()
def page(request: pytest.FixtureRequest, config: Config) -> Iterator[Page]:
    factory = BrowserFactory(config)
    browser_page = factory.start()
    try:
        yield browser_page
    finally:
        if config.reporting.screenshot_on_failure and request.node.rep_call_failed:
            target = config.screenshots_path() / f"FAILED_{request.node.name}.png"
            try:
                browser_page.screenshot(path=str(target), full_page=True)
                _LOG.error("Failure screenshot: %s", target)
            except Exception as exc:  # pragma: no cover
                _LOG.warning("Could not capture the failure screenshot: %s", exc)
        factory.stop(trace_name=request.node.name)


@pytest.fixture()
def flow(page: Page, config: Config, rng: random.Random) -> ShoppingFlow:
    return ShoppingFlow(page=page, config=config, rng=rng)


# --------------------------------------------------- failure-aware teardown --
@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.rep_call_failed = report.failed


@pytest.fixture(autouse=True)
def _default_failure_flag(request: pytest.FixtureRequest) -> None:
    request.node.rep_call_failed = False
