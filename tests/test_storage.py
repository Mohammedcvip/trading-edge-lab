"""Tests for CandleStore (src.storage): dedup, resume pointer, range reads."""

from __future__ import annotations

import pytest

from src.models import CandleValidationError
from src.storage import CandleStore
from tests.conftest import make_candle


def test_save_and_read_roundtrip(tmp_db: str) -> None:
    with CandleStore(tmp_db) as store:
        candles = [make_candle(i * 3_600_000) for i in range(3)]
        assert store.save_candles(candles) == 3
        stored = store.read_candles("BTCUSDT", "1h")
        assert [c.open_time for c in stored] == [0, 3_600_000, 7_200_000]
        # floats converted from provider strings survive the round trip
        assert stored[0].close == pytest.approx(105.0)


def test_duplicates_ignored_safely(tmp_db: str) -> None:
    candle = make_candle(0)
    with CandleStore(tmp_db) as store:
        assert store.save_candles([candle]) == 1
        assert store.save_candles([candle, candle]) == 0  # no error, no new rows
        assert len(store.read_candles("BTCUSDT", "1h")) == 1


def test_latest_open_time(tmp_db: str) -> None:
    with CandleStore(tmp_db) as store:
        assert store.latest_open_time("BTCUSDT", "1h") is None
        store.save_candles([make_candle(0), make_candle(2 * 3_600_000)])
        assert store.latest_open_time("BTCUSDT", "1h") == 2 * 3_600_000
        # other series unaffected
        assert store.latest_open_time("ETHUSDT", "1h") is None


def test_read_candles_respects_range(tmp_db: str) -> None:
    with CandleStore(tmp_db) as store:
        store.save_candles([make_candle(i * 3_600_000) for i in range(5)])
        window = store.read_candles("BTCUSDT", "1h", start_ms=3_600_000, end_ms=10_800_000)
        assert [c.open_time for c in window] == [3_600_000, 7_200_000, 10_800_000]


def test_invalid_candle_not_stored(tmp_db: str) -> None:
    bad = make_candle(0, high=1.0)
    store = CandleStore(tmp_db)
    try:
        with pytest.raises(CandleValidationError):
            store.save_candles([bad])
        assert store.read_candles("BTCUSDT", "1h") == []
    finally:
        store.close()
