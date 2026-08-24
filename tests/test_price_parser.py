"""Offline unit tests for the price parser - no browser, runs in milliseconds."""
from __future__ import annotations

import pytest

from src.core.price_parser import PriceParser


@pytest.mark.unit
@pytest.mark.parametrize(
    "text, expected",
    [
        ("$24.99", 24.99),
        ("US $1,299.00", 1299.00),
        ("$18.50 to $32.00", 18.50),
        ("GBP 15.00", 15.00),
        ("$1.234,56", 1234.56),
        ("EUR 9,99", 9.99),
        ("$0.99", 0.99),
        ("Free", None),
        ("", None),
        (None, None),
    ],
)
def test_parse(text, expected):
    assert PriceParser.parse(text) == expected


@pytest.mark.unit
def test_is_range():
    assert PriceParser.is_range("$18.50 to $32.00")
    assert not PriceParser.is_range("$18.50")


@pytest.mark.unit
def test_first_within():
    assert PriceParser.first_within(["$300", "$120", "$90"], 150) == 120.0
    assert PriceParser.first_within(["$300", "$280"], 150) is None
