"""Command-line entry point for Stage 1: fetch and check candle data."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from src.config import DEFAULT_DAYS, DEFAULT_SYMBOLS, DB_PATH, SUPPORTED_INTERVALS
from src.ingestion import ingest
from src.integrity import check_store, format_report
from src.providers.binance import MAX_KLINES_PER_REQUEST, BinanceProvider, ProviderError
from src.storage import CandleStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-edge-lab",
        description="Stage 1: fetch and verify historical crypto candles.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--symbols", nargs="+", default=list(DEFAULT_SYMBOLS), metavar="SYMBOL",
        help=f"Symbols to process (default: {' '.join(DEFAULT_SYMBOLS)})",
    )
    common.add_argument(
        "--intervals", nargs="+", default=list(SUPPORTED_INTERVALS),
        metavar="INTERVAL",
        help=f"Candle intervals; supported: {', '.join(SUPPORTED_INTERVALS)}",
    )

    fetch = sub.add_parser("fetch", parents=[common], help="Download and store candles.")
    fetch.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"History window in days (default: {DEFAULT_DAYS})",
    )
    fetch.add_argument(
        "--db", type=str, default=str(DB_PATH),
        help=f"SQLite database path (default: {DB_PATH})",
    )

    sub.add_parser("check", parents=[common], help="Print a data-integrity report.")
    return parser


def _validate(intervals: Sequence[str]) -> str | None:
    bad = [i for i in intervals if i not in SUPPORTED_INTERVALS]
    if bad:
        return (
            f"unsupported interval(s): {', '.join(bad)}; "
            f"supported: {', '.join(SUPPORTED_INTERVALS)}"
        )
    if not intervals:
        return "at least one interval is required"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    error = _validate(args.intervals)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.command == "fetch" and args.days <= 0:
        print("error: --days must be positive", file=sys.stderr)
        return 2

    symbols = [s.upper() for s in args.symbols]

    with CandleStore(args.db if args.command == "fetch" else DB_PATH) as store:
        if args.command == "fetch":
            provider = BinanceProvider()
            try:
                for symbol in symbols:
                    for interval in args.intervals:
                        result = ingest(
                            provider=provider,
                            store=store,
                            symbol=symbol,
                            interval=interval,
                            days=args.days,
                            page_limit=MAX_KLINES_PER_REQUEST,
                        )
                        print(
                            f"fetched {result.symbol} {result.interval}: "
                            f"received={result.fetched} stored_new={result.stored} "
                            f"skipped_open={result.skipped_open} "
                            f"skipped_duplicate={result.skipped_duplicate}"
                        )
            except ProviderError as exc:
                print(f"error: provider failure: {exc}", file=sys.stderr)
                return 1
            return 0

        # check
        reports = check_store(store, symbols, args.intervals)
        for report in reports:
            print(format_report(report))
        return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
