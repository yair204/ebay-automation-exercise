"""Parsing of the many shapes eBay prints prices in.

Handled forms::

    "$24.99"                 -> 24.99
    "US $1,299.00"           -> 1299.0
    "$18.50 to $32.00"       -> 18.50   (a range: the lowest price wins)
    "GBP 15.00"              -> 15.0
    "$1.234,56"              -> 1234.56 (European grouping)
    "Free"/""                -> None
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

# A number with optional thousands separators and an optional decimal part.
_NUMBER_RE = re.compile(r"\d[\d.,\s ]*\d|\d")
_RANGE_SEPARATORS = re.compile(r"\bto\b|/|–|—|-", re.IGNORECASE)


class PriceParser:
    """Stateless helper - kept as a class so it can be injected/stubbed in tests."""

    @staticmethod
    def _normalize_number(token: str) -> Optional[float]:
        token = token.replace(" ", "").replace(" ", "").strip()
        if not token:
            return None

        last_dot, last_comma = token.rfind("."), token.rfind(",")
        if last_dot == -1 and last_comma == -1:
            cleaned = token
        elif last_comma > last_dot:
            # European style: "1.234,56" -> comma is the decimal separator
            cleaned = token.replace(".", "").replace(",", ".")
        else:
            # US/UK style: "1,234.56" -> comma groups thousands
            cleaned = token.replace(",", "")

        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def parse(cls, text: Optional[str]) -> Optional[float]:
        """Return the *lowest* price found in ``text``, or ``None``.

        The lowest value of a range is deliberate: a listing shown as
        "$18.50 to $32.00" has at least one variant at or under $18.50, and the
        variant selection step later picks a concrete one that we re-validate.
        """
        values = cls.parse_all(text)
        return min(values) if values else None

    @classmethod
    def parse_all(cls, text: Optional[str]) -> List[float]:
        if not text:
            return []
        values = [cls._normalize_number(m.group()) for m in _NUMBER_RE.finditer(text)]
        return [v for v in values if v is not None]

    @classmethod
    def is_range(cls, text: Optional[str]) -> bool:
        return bool(text) and len(cls.parse_all(text)) > 1 and bool(_RANGE_SEPARATORS.search(text or ""))

    @classmethod
    def first_within(cls, texts: Iterable[Optional[str]], max_price: float) -> Optional[float]:
        for text in texts:
            value = cls.parse(text)
            if value is not None and value <= max_price:
                return value
        return None
