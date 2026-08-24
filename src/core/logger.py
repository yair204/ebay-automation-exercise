"""Single logging entry point for the whole framework."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s"


def _configure(log_file: Path | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format=_FORMAT, handlers=handlers)
    _CONFIGURED = True


def get_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    _configure(log_file)
    return logging.getLogger(name)
