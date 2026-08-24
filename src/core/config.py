"""Configuration loading: YAML base file + profile overlay + ENV overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class ViewportConfig:
    width: int = 1920
    height: int = 1080


@dataclass(frozen=True)
class BrowserConfig:
    name: str = "chromium"
    headless: bool = True
    slow_mo_ms: int = 0
    viewport: ViewportConfig = field(default_factory=ViewportConfig)
    default_timeout_ms: int = 20000
    navigation_timeout_ms: int = 45000


@dataclass(frozen=True)
class AppConfig:
    base_url: str = "https://www.ebay.com"
    currency_symbol: str = "$"
    locale: str = "en-US"


@dataclass(frozen=True)
class AuthConfig:
    strategy: str = "guest"
    username: str = ""
    password: str = ""


@dataclass(frozen=True)
class ReportingConfig:
    screenshots_dir: str = "reports/screenshots"
    traces_dir: str = "reports/traces"
    record_trace: bool = True
    screenshot_on_failure: bool = True


@dataclass(frozen=True)
class RuntimeConfig:
    max_pages_to_scan: int = 5
    retries: int = 2


@dataclass(frozen=True)
class Config:
    """Immutable, typed view over the merged configuration."""

    app: AppConfig
    browser: BrowserConfig
    auth: AuthConfig
    reporting: ReportingConfig
    runtime: RuntimeConfig
    profile: str

    # -- paths resolved against the repo root, so the suite is CWD independent
    def screenshots_path(self) -> Path:
        return self._ensure(ROOT / self.reporting.screenshots_dir)

    def traces_path(self) -> Path:
        return self._ensure(ROOT / self.reporting.traces_dir)

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path


class ConfigLoader:
    """Builds a :class:`Config`. Precedence: ENV > profile YAML > base YAML."""

    _ENV_MAP = {
        "BASE_URL": ("app", "base_url", str),
        "CURRENCY_SYMBOL": ("app", "currency_symbol", str),
        "BROWSER": ("browser", "name", str),
        "HEADLESS": ("browser", "headless", _as_bool),
        "SLOW_MO_MS": ("browser", "slow_mo_ms", int),
        "DEFAULT_TIMEOUT_MS": ("browser", "default_timeout_ms", int),
        "AUTH_STRATEGY": ("auth", "strategy", str),
        "EBAY_USER": ("auth", "username", str),
        "EBAY_PASS": ("auth", "password", str),
        "RECORD_TRACE": ("reporting", "record_trace", _as_bool),
        "MAX_PAGES_TO_SCAN": ("runtime", "max_pages_to_scan", int),
    }

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or (ROOT / "config")

    def load(self) -> Config:
        load_dotenv(ROOT / ".env", override=False)
        profile = os.getenv("PROFILE", "").strip()

        raw = self._read_yaml(self._config_dir / "config.yaml")
        if profile:
            overlay_file = self._config_dir / f"config.{profile}.yaml"
            if overlay_file.exists():
                raw = _deep_merge(raw, self._read_yaml(overlay_file))

        raw = self._apply_env(raw)
        return self._to_dataclass(raw, profile or "default")

    @staticmethod
    def _read_yaml(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _apply_env(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        for env_name, (section, key, caster) in self._ENV_MAP.items():
            value = os.getenv(env_name)
            if value is None or value == "":
                continue
            raw.setdefault(section, {})[key] = caster(value)
        return raw

    @staticmethod
    def _to_dataclass(raw: Dict[str, Any], profile: str) -> Config:
        browser_raw = dict(raw.get("browser", {}))
        viewport = ViewportConfig(**browser_raw.pop("viewport", {}) or {})
        return Config(
            app=AppConfig(**raw.get("app", {})),
            browser=BrowserConfig(viewport=viewport, **browser_raw),
            auth=AuthConfig(**raw.get("auth", {})),
            reporting=ReportingConfig(**raw.get("reporting", {})),
            runtime=RuntimeConfig(**raw.get("runtime", {})),
            profile=profile,
        )


_cached: Config | None = None


def get_config() -> Config:
    """Process-wide singleton so every layer sees the same configuration."""
    global _cached
    if _cached is None:
        _cached = ConfigLoader().load()
    return _cached
