"""Shared pytest fixtures and helpers (offline only)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.models import Candle


def make_candle(
    open_time: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    *,
    open: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: float = 1.0,
    close_time: int | None = None,
    quote_volume: float = 105.0,
    trades: int = 10,
) -> Candle:
    """Build a valid candle; override any field to create test cases."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        close_time=close_time if close_time is not None else open_time + 3_600_000,
        quote_volume=quote_volume,
        trades=trades,
    )


@pytest.fixture
def tmp_db(tmp_path) -> Iterator[str]:
    yield str(tmp_path / "test.db")
