"""Unit tests for integrity checks (src.integrity)."""

from __future__ import annotations

from src.integrity import check_series, format_report
from tests.conftest import make_candle
from tests.fakes import hourly_series

STEP = 3_600_000


def test_clean_series_is_ok() -> None:
    report = check_series(hourly_series(0, 5), "BTCUSDT", "1h")
    assert report.ok
    assert report.count == 5
    assert report.gaps == []


def test_gap_detected_with_exact_count() -> None:
    # skip candles at index 2 and 3 -> two missing between idx1 and idx4
    candles = hourly_series(0, 6, missing={2, 3})
    report = check_series(candles, "BTCUSDT", "1h")
    assert not report.ok
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.missing_count == 2
    assert gap.after_open_time == STEP
    assert gap.before_open_time == 4 * STEP


def test_multiple_gaps_detected() -> None:
    candles = hourly_series(0, 6, missing={1, 4})
    report = check_series(candles, "BTCUSDT", "1h")
    assert len(report.gaps) == 2
    assert sum(g.missing_count for g in report.gaps) == 2


def test_value_violation_reported() -> None:
    good = hourly_series(0, 3)
    bad = make_candle(3 * STEP, high=10.0)  # high < low
    report = check_series([*good, bad], "BTCUSDT", "1h")
    assert not report.ok
    assert len(report.value_violations) == 1
    assert report.value_violations[0].open_time == 3 * STEP
    assert "high" in report.value_violations[0].reason


def test_out_of_order_detected() -> None:
    candles = hourly_series(0, 3)
    shuffled = [candles[1], candles[0], candles[2]]
    report = check_series(shuffled, "BTCUSDT", "1h")
    assert report.out_of_order
    # ordering itself must not be reported as a gap after sorting
    assert report.gaps == []


def test_empty_series_is_ok_but_zero() -> None:
    report = check_series([], "BTCUSDT", "1h")
    assert report.ok
    assert report.count == 0
    assert report.first_open_time is None


def test_format_report_mentions_numbers() -> None:
    report = check_series(hourly_series(0, 6, missing={2}), "BTCUSDT", "1h")
    text = format_report(report)
    assert "candles=5" in text
    assert "GAP" in text
    assert "status=PROBLEMS" in text
