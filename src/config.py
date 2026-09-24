"""Central configuration constants for Trading Edge Lab (Stage 1: data infrastructure)."""

from pathlib import Path

# Supported candle intervals and their duration in milliseconds.
SUPPORTED_INTERVALS: tuple[str, ...] = ("15m", "1h", "4h")

INTERVAL_MS: dict[str, int] = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}

# Default symbols to ingest when the CLI is not given explicit ones.
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")

# Default history window to backfill, in days.
DEFAULT_DAYS: int = 730

# A candle counts as closed only when close_time < now - this margin, so a
# candle that just barely crossed its nominal close time is never stored with
# potentially incomplete data (clock skew / late final trades).
CLOSED_CANDLE_SAFETY_MARGIN_MS: int = 5000

# SQLite database location (relative to the repository root).
DB_PATH: Path = Path("data") / "candles.db"
