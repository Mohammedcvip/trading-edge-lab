"""Paginated ingestion of historical candles into the store."""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.config import CLOSED_CANDLE_SAFETY_MARGIN_MS, INTERVAL_MS
from src.models import Candle
from src.providers.base import MarketDataProvider
from src.storage import CandleStore

MS_PER_DAY = 24 * 60 * 60 * 1000


@dataclass(frozen=True, slots=True)
class IngestionResult:
    symbol: str
    interval: str
    fetched: int
    stored: int
    skipped_open: int
    skipped_duplicate: int


def _closed_only(
    candles: list[Candle], now_ms: int, margin_ms: int = CLOSED_CANDLE_SAFETY_MARGIN_MS
) -> tuple[list[Candle], int]:
    """Split off candles that are not safely closed yet.

    A candle counts as closed only when close_time < now_ms - margin_ms
    (strictly less), so a candle that just crossed its nominal close time is
    never stored while it could still receive late trades.
    """
    cutoff = now_ms - margin_ms
    closed = [c for c in candles if c.close_time < cutoff]
    return closed, len(candles) - len(closed)


def ingest(
    provider: MarketDataProvider,
    store: CandleStore,
    symbol: str,
    interval: str,
    days: int,
    page_limit: int,
    now_ms: int | None = None,
) -> IngestionResult:
    """Backfill `days` of history for one (symbol, interval), resuming as needed.

    Pagination walks forward from the requested window start (or from just after
    the last stored candle when resuming), fetching at most `page_limit` candles
    per request. Only closed candles are stored; duplicates are ignored safely.
    """
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    if days <= 0:
        raise ValueError("days must be positive")
    if page_limit <= 0:
        raise ValueError("page_limit must be positive")

    now = now_ms if now_ms is not None else int(time.time() * 1000)
    step = INTERVAL_MS[interval]

    window_start = now - days * MS_PER_DAY
    last = store.latest_open_time(symbol, interval)
    resume_from = window_start if last is None else max(window_start, last + step)

    fetched = stored = skipped_open = 0
    start = resume_from
    while start < now:
        batch = provider.fetch_klines(
            symbol=symbol, interval=interval, start_ms=start, limit=page_limit
        )
        if not batch:
            break
        batch.sort(key=lambda c: c.open_time)
        # `fetched` counts every candle received from the provider (closed and
        # open alike); `skipped_open` counts the ones dropped as not closed.
        fetched += len(batch)
        closed, dropped = _closed_only(batch, now)
        skipped_open += dropped

        stored += store.save_candles(closed)

        # Advance strictly past the last seen open_time to guarantee progress.
        start = batch[-1].open_time + step
        if len(batch) < page_limit:
            break  # reached the current tip of the series

    return IngestionResult(
        symbol=symbol.upper(),
        interval=interval,
        fetched=fetched,
        stored=stored,
        skipped_open=skipped_open,
        # closed candles that were not new rows -> already present in the store
        skipped_duplicate=max(0, fetched - skipped_open - stored),
    )
