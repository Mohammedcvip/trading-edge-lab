"""Offline fake provider and series builders shared by the test suite."""

from __future__ import annotations

import dataclasses

from src.config import INTERVAL_MS
from src.models import Candle
from src.providers.base import MarketDataProvider


class FakeProvider(MarketDataProvider):
    """Serves a fixed candle series from memory in page_limit-sized windows.

    No network access; behaves like Binance klines: returns candles whose
    open_time >= start_ms, oldest first, at most `limit` of them.
    """

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = sorted(candles, key=lambda c: c.open_time)
        self.calls: list[tuple[int | None, int | None]] = []

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        self.calls.append((start_ms, limit))
        out: list[Candle] = []
        for candle in self._candles:
            if candle.symbol != symbol or candle.interval != interval:
                continue
            if start_ms is not None and candle.open_time < start_ms:
                continue
            if end_ms is not None and candle.open_time > end_ms:
                continue
            out.append(dataclasses.replace(candle, symbol=symbol))
            if limit is not None and len(out) >= limit:
                break
        return out


def hourly_series(start_ms: int, count: int, missing: set[int] | None = None) -> list[Candle]:
    """Generate `count` consecutive 1h candles starting at start_ms.

    `missing` indexes are skipped to simulate gaps. A trailing in-progress
    candle (close_time = start + (count+1)*step, i.e. beyond 'now') can be
    appended by callers via make_candle directly.
    """
    missing = missing or set()
    step = INTERVAL_MS["1h"]
    candles: list[Candle] = []
    for i in range(count):
        if i in missing:
            continue
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time=start_ms + i * step,
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=1.0,
                close_time=start_ms + (i + 1) * step - 1,
                quote_volume=105.0,
                trades=10,
            )
        )
    return candles
