"""Data-integrity checks over stored candles."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import INTERVAL_MS
from src.models import Candle, CandleValidationError
from src.storage import CandleStore


@dataclass(frozen=True, slots=True)
class Gap:
    """A missing run of candles between two consecutive stored candles."""

    after_open_time: int
    before_open_time: int
    missing_count: int


@dataclass(frozen=True, slots=True)
class ValueViolation:
    open_time: int
    reason: str


@dataclass(frozen=True, slots=True)
class SeriesReport:
    symbol: str
    interval: str
    count: int
    first_open_time: int | None
    last_open_time: int | None
    gaps: list[Gap] = field(default_factory=list)
    value_violations: list[ValueViolation] = field(default_factory=list)
    out_of_order: bool = False

    @property
    def ok(self) -> bool:
        return (
            not self.gaps
            and not self.value_violations
            and not self.out_of_order
        )


def check_series(candles: list[Candle], symbol: str, interval: str) -> SeriesReport:
    """Analyse one series for ordering, gaps, and per-candle value violations."""
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    step = INTERVAL_MS[interval]

    ordered = sorted(candles, key=lambda c: c.open_time)
    out_of_order = any(
        a.open_time > b.open_time for a, b in zip(candles, candles[1:])
    )

    gaps: list[Gap] = []
    for prev, nxt in zip(ordered, ordered[1:]):
        expected = prev.open_time + step
        if nxt.open_time != expected:
            missing = max(0, (nxt.open_time - expected) // step)
            gaps.append(
                Gap(
                    after_open_time=prev.open_time,
                    before_open_time=nxt.open_time,
                    missing_count=missing,
                )
            )

    violations: list[ValueViolation] = []
    for candle in ordered:
        try:
            candle.validate()
        except CandleValidationError as exc:
            violations.append(ValueViolation(candle.open_time, str(exc)))

    return SeriesReport(
        symbol=symbol.upper(),
        interval=interval,
        count=len(candles),
        first_open_time=ordered[0].open_time if ordered else None,
        last_open_time=ordered[-1].open_time if ordered else None,
        gaps=gaps,
        value_violations=violations,
        out_of_order=out_of_order,
    )


def check_store(
    store: CandleStore, symbols: list[str], intervals: list[str]
) -> list[SeriesReport]:
    """Run check_series for every requested (symbol, interval) pair."""
    reports: list[SeriesReport] = []
    for symbol in symbols:
        for interval in intervals:
            candles = store.read_candles(symbol, interval)
            reports.append(check_series(candles, symbol, interval))
    return reports


def format_report(report: SeriesReport) -> str:
    """Human-readable, numeric summary of one series report."""
    lines = [
        f"[{report.symbol} {report.interval}] "
        f"candles={report.count} "
        f"range=({report.first_open_time}, {report.last_open_time}) "
        f"status={'OK' if report.ok else 'PROBLEMS'}"
    ]
    if report.out_of_order:
        lines.append("  - times are not strictly ascending as stored")
    for gap in report.gaps:
        lines.append(
            f"  - GAP: {gap.missing_count} missing candle(s) between "
            f"{gap.after_open_time} and {gap.before_open_time}"
        )
    for violation in report.value_violations:
        lines.append(f"  - BAD VALUES at {violation.open_time}: {violation.reason}")
    return "\n".join(lines)
