"""Unit tests for Candle validation (src.models)."""

from __future__ import annotations

import dataclasses

import pytest

from src.models import Candle, CandleValidationError
from tests.conftest import make_candle


def test_valid_candle_passes() -> None:
    make_candle(0).validate()  # must not raise


@pytest.mark.parametrize(
    "field, value",
    [
        ("high", 89.0),   # high < low
        ("low", 111.0),   # low > high
        ("volume", -1.0),
        ("open", 0.0),    # non-positive price
        ("close", -5.0),
    ],
)
def test_invalid_values_rejected(field: str, value: float) -> None:
    base = make_candle(0)
    bad = dataclasses.replace(base, **{field: value})
    with pytest.raises(CandleValidationError):
        bad.validate()


def test_high_below_close_rejected() -> None:
    bad = make_candle(0, open=100.0, high=104.0, low=90.0, close=105.0)
    with pytest.raises(CandleValidationError, match="high"):
        bad.validate()


def test_low_above_open_rejected() -> None:
    bad = make_candle(0, open=100.0, high=110.0, low=101.0, close=95.0)
    with pytest.raises(CandleValidationError, match="low"):
        bad.validate()


def test_negative_trades_rejected() -> None:
    bad = make_candle(0, trades=-1)
    with pytest.raises(CandleValidationError):
        bad.validate()
