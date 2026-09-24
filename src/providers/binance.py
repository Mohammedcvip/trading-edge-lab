"""Binance public market-data provider (spot klines, no API keys required)."""

from __future__ import annotations

import time
from typing import Any

import requests

from src.config import SUPPORTED_INTERVALS
from src.models import Candle, CandleValidationError
from src.providers.base import MarketDataProvider

BASE_URL = "https://data-api.binance.vision"
KLINES_PATH = "/api/v3/klines"

# The default limit is 500 and the maximum is 1000 klines per request. These
# numbers come from documentation of client libraries built against the Binance
# specs; they were NOT verified directly against developers.binance.com.
DEFAULT_KLINES_LIMIT = 500
MAX_KLINES_PER_REQUEST = 1000

DEFAULT_TIMEOUT_S = 30.0
MAX_ATTEMPTS = 5
INITIAL_BACKOFF_S = 1.0


class ProviderError(RuntimeError):
    """Raised when the provider cannot return usable data."""


class BinanceProvider(MarketDataProvider):
    """Fetches spot klines from the public Binance data endpoint."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_attempts: int = MAX_ATTEMPTS,
        backoff_s: float = INITIAL_BACKOFF_S,
        sleep: Any = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self._backoff_s = backoff_s
        self._sleep = sleep

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(
                f"unsupported interval {interval!r}; expected one of {SUPPORTED_INTERVALS}"
            )
        if limit is not None and not 1 <= limit <= MAX_KLINES_PER_REQUEST:
            raise ValueError(
                f"limit must be between 1 and {MAX_KLINES_PER_REQUEST}, got {limit}"
            )
        if start_ms is not None and end_ms is not None and start_ms > end_ms:
            raise ValueError("start_ms must not be greater than end_ms")

        params: dict[str, Any] = {"symbol": symbol.upper(), "interval": interval}
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        params["limit"] = limit if limit is not None else MAX_KLINES_PER_REQUEST

        payload = self._get_json(f"{BASE_URL}{KLINES_PATH}", params)
        if not isinstance(payload, list):
            raise ProviderError(f"unexpected response shape: {type(payload).__name__}")
        return [self._parse_row(row, symbol.upper(), interval) for row in payload]

    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        """GET with retries on HTTP 429 / 5xx, honouring Retry-After when present."""
        last_error = "unknown error"
        for attempt in range(self._max_attempts):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout_s)
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
                self._wait(attempt, retry_after=None)
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ProviderError(f"invalid JSON in response: {exc}") from exc

            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                self._wait(attempt, retry_after=self._retry_after_seconds(response))
                continue

            # Non-retryable client error (400 bad symbol/interval, 451, etc.)
            raise ProviderError(f"HTTP {response.status_code}: {response.text[:200]}")

        raise ProviderError(
            f"giving up after {self._max_attempts} attempts; last error: {last_error}"
        )

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None  # HTTP-date form not needed for this endpoint

    def _wait(self, attempt: int, retry_after: float | None) -> None:
        if attempt == self._max_attempts - 1:
            return
        delay = self._backoff_s * (2**attempt)
        if retry_after is not None:
            delay = max(delay, retry_after)
        self._sleep(delay)

    @staticmethod
    def _parse_row(row: Any, symbol: str, interval: str) -> Candle:
        if not isinstance(row, list) or len(row) < 11:
            raise ProviderError(f"malformed kline row (too short): {row!r}")
        try:
            candle = Candle(
                symbol=symbol,
                interval=interval,
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=int(row[6]),
                quote_volume=float(row[7]),
                trades=int(row[8]),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"unparsable kline row {row!r}: {exc}") from exc
        try:
            candle.validate()
        except CandleValidationError as exc:
            # a provider row that fails validation is malformed data
            raise ProviderError(str(exc)) from exc
        return candle
