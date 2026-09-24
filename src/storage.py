"""SQLite persistence layer for candles."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.models import Candle

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol       TEXT    NOT NULL,
    interval     TEXT    NOT NULL,
    open_time    INTEGER NOT NULL,
    open         REAL    NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    close        REAL    NOT NULL,
    volume       REAL    NOT NULL,
    close_time   INTEGER NOT NULL,
    quote_volume REAL    NOT NULL,
    trades       INTEGER NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
);
"""


class CandleStore:
    """Reads and writes validated candles in a SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        try:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except Exception:
            self._conn.close()  # never leave a broken store open
            raise

    def save_candles(self, candles: list[Candle]) -> int:
        """Insert a batch of candles, silently skipping duplicates.

        The whole batch is one transaction: if any candle fails validation
        nothing is written. Returns the number of rows actually inserted.
        """
        if not candles:
            return 0
        rows = []
        for candle in candles:
            candle.validate()
            rows.append(
                (
                    candle.symbol,
                    candle.interval,
                    candle.open_time,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.close_time,
                    candle.quote_volume,
                    candle.trades,
                )
            )
        before = self._count()
        try:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO candles
                    (symbol, interval, open_time, open, high, low, close,
                     volume, close_time, quote_volume, trades)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self._count() - before

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CandleStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def latest_open_time(self, symbol: str, interval: str) -> int | None:
        """Return the newest stored open_time for (symbol, interval), or None."""
        row = self._conn.execute(
            "SELECT MAX(open_time) FROM candles WHERE symbol = ? AND interval = ?",
            (symbol.upper(), interval),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def read_candles(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[Candle]:
        """Return stored candles with open_time in [start_ms, end_ms], oldest first."""
        query = (
            "SELECT symbol, interval, open_time, open, high, low, close, volume, "
            "close_time, quote_volume, trades FROM candles "
            "WHERE symbol = ? AND interval = ?"
        )
        params: list[object] = [symbol.upper(), interval]
        if start_ms is not None:
            query += " AND open_time >= ?"
            params.append(int(start_ms))
        if end_ms is not None:
            query += " AND open_time <= ?"
            params.append(int(end_ms))
        query += " ORDER BY open_time ASC"
        return [Candle(*row) for row in self._conn.execute(query, params)]

    def _count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM candles").fetchone()
        return int(row[0])
