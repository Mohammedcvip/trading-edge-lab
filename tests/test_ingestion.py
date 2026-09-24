"""Tests for ingestion (src.ingestion): pagination, open-candle skip, resume."""

from __future__ import annotations

import pytest

from src.ingestion import ingest
from src.storage import CandleStore
from tests.conftest import make_candle
from tests.fakes import FakeProvider, hourly_series

STEP = 3_600_000
DAY = 24 * STEP
# Anchored to a round epoch multiple so that `now - days*DAY` always lands on
# an exact candle boundary (hourly_series starts at t=0). The last candle of
# _closed_series nominally closes at NOW-1, which is inside the closed-candle
# safety margin, so it is intentionally never stored; TIP is the newest candle
# that satisfies close_time < now - CLOSED_CANDLE_SAFETY_MARGIN_MS.
NOW = 5000 * DAY
TIP = NOW - 2 * STEP


def _closed_series(count: int) -> list:
    """Count consecutive closed 1h candles ending just before NOW."""
    return hourly_series(NOW - count * STEP, count)


def test_skips_open_candle(tmp_db: str) -> None:
    # include an in-progress candle whose close_time is beyond NOW
    open_candle = make_candle(NOW, close_time=NOW + STEP - 1)
    provider = FakeProvider([*_closed_series(5), open_candle])
    with CandleStore(tmp_db) as store:
        result = ingest(
            provider, store, "BTCUSDT", "1h",
            days=1, page_limit=10, now_ms=NOW + 10,
        )
        # received 6; skipped 2 as not safely closed (the open one + the one
        # closing inside the safety margin); stored the 4 older ones
        assert result.skipped_open == 2
        assert result.stored == 4
        assert store.latest_open_time("BTCUSDT", "1h") == TIP


def test_closed_safety_margin_boundary(tmp_db: str) -> None:
    """A candle is stored only if close_time < now - CLOSED_CANDLE_SAFETY_MARGIN_MS."""
    from src.config import CLOSED_CANDLE_SAFETY_MARGIN_MS as MARGIN

    base = NOW - 10 * STEP
    # closed less than the margin ago -> must NOT be stored
    too_recent = make_candle(base, close_time=NOW - 1)
    assert NOW - too_recent.close_time < MARGIN
    # closed more than the margin ago -> must be stored
    old_enough = make_candle(base + STEP, close_time=NOW - MARGIN - 1)
    assert NOW - old_enough.close_time > MARGIN

    provider = FakeProvider([old_enough, too_recent])
    with CandleStore(tmp_db) as store:
        result = ingest(provider, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        assert result.stored == 1
        assert result.skipped_open == 1
        assert store.read_candles("BTCUSDT", "1h") == [old_enough]


def test_report_counts_open_and_duplicate(tmp_db: str) -> None:
    """fetched = all received (closed+open); skipped_duplicate = closed rows already stored."""
    series = _closed_series(5)
    # in-progress candle whose close_time is beyond NOW
    open_candle = make_candle(NOW + STEP, close_time=NOW + 2 * STEP - 1)
    provider = FakeProvider([*series, open_candle])
    with CandleStore(tmp_db) as store:
        first = ingest(provider, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        # 6 received; 2 skipped-open (within-margin tip s4 + in-progress s5);
        # the 4 older candles stored new
        assert (first.fetched, first.stored, first.skipped_open, first.skipped_duplicate) == (
            6, 4, 2, 0,
        )
        # rewind the DB to its oldest stored candle WITHOUT touching the
        # newest row (s3 stays): the resume pointer remains at the tip, so
        # the next run re-reads the whole stored range -> s3 comes back as a
        # duplicate while the deleted s0..s2 are re-inserted as new rows.
        store._conn.execute(
            "DELETE FROM candles WHERE symbol='BTCUSDT' AND interval='1h' "
            "AND open_time < ?",
            (series[-1].open_time,),
        )
        store._conn.commit()
        second = ingest(provider, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        # received 6 again; 2 skipped-open; 3 newly stored; 1 duplicate (s3)
        assert (second.fetched, second.stored, second.skipped_open, second.skipped_duplicate) == (
            6, 3, 2, 1,
        )


def test_pagination_walks_full_window(tmp_db: str) -> None:
    provider = FakeProvider(_closed_series(50))
    with CandleStore(tmp_db) as store:
        result = ingest(
            provider, store, "BTCUSDT", "1h",
            days=2, page_limit=10, now_ms=NOW,
        )
        # days=2 -> window = the last 48 of the 50 available candles
        assert result.fetched == 48
        assert result.stored == 47  # the last one closes within the safety margin
        assert len(provider.calls) == 5  # pages of 10,10,10,10,8 (short page ends walk)
        assert store.latest_open_time("BTCUSDT", "1h") == TIP


def test_resumes_from_last_stored_candle(tmp_db: str) -> None:
    with CandleStore(tmp_db) as store:
        # first run stores the newest candles ending just before NOW
        provider1 = FakeProvider(_closed_series(20))
        ingest(provider1, store, "BTCUSDT", "1h", days=20, page_limit=10, now_ms=NOW)
        assert store.latest_open_time("BTCUSDT", "1h") == TIP

        # second run must not re-request anything before the tip
        provider2 = FakeProvider(_closed_series(30))
        result2 = ingest(
            provider2, store, "BTCUSDT", "1h",
            days=30, page_limit=10, now_ms=NOW,
        )
        starts = [call[0] for call in provider2.calls]
        assert min(starts) >= TIP + STEP  # never re-request before the tip
        assert result2.stored == 0               # nothing newer exists yet
        assert store.latest_open_time("BTCUSDT", "1h") == TIP


def test_backfills_gap_older_than_tip(tmp_db: str) -> None:
    """A hole older than the tip is filled without regressing the pointer."""
    with CandleStore(tmp_db) as store:
        # series missing its oldest candle -> 8 stored (tip within margin excluded)
        provider = FakeProvider(_closed_series(10)[1:])
        r1 = ingest(provider, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        assert r1.stored == 8

        # full series now includes the old gap; resume starts at the tip so no
        # duplicate work happens on the fresh tail
        full = FakeProvider(_closed_series(10))
        r2 = ingest(full, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        assert r2.stored == 0
        assert r2.fetched <= 10  # at most one short page from the tip onward


def test_reingest_same_range_counts_duplicates(tmp_db: str) -> None:
    with CandleStore(tmp_db) as store:
        provider = FakeProvider(_closed_series(10))
        ingest(provider, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        result = ingest(provider, store, "BTCUSDT", "1h", days=1, page_limit=10, now_ms=NOW)
        # resume pointer means nothing new to fetch past the tip
        assert result.stored == 0


def test_empty_provider_result_stops(tmp_db: str) -> None:
    provider = FakeProvider([])
    with CandleStore(tmp_db) as store:
        result = ingest(provider, store, "BTCUSDT", "1h", days=5, page_limit=10, now_ms=NOW)
        assert result.fetched == 0 and result.stored == 0


def test_rejects_bad_args(tmp_db: str) -> None:
    provider = FakeProvider([])
    with CandleStore(tmp_db) as store, pytest.raises(ValueError):
        ingest(provider, store, "BTCUSDT", "5m", days=5, page_limit=10, now_ms=NOW)
    with pytest.raises(ValueError):
        ingest(provider, store, "BTCUSDT", "1h", days=0, page_limit=10, now_ms=NOW)
    with pytest.raises(ValueError):
        ingest(provider, store, "BTCUSDT", "1h", days=5, page_limit=0, now_ms=NOW)
