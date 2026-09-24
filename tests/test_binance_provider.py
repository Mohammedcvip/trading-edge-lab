"""Offline tests for BinanceProvider parsing and retry behaviour."""

from __future__ import annotations

import pytest
import requests

from src.providers.binance import MAX_KLINES_PER_REQUEST, BinanceProvider, ProviderError


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Queue of responses; records each request's params."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.requests.append({"url": url, "params": params})
        if not self._responses:
            raise AssertionError("more requests than queued responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


ROW = [1790197200000, "84232.86", "84516.01", "84212.68", "84419.48",
       "416.52", 1790200799999, "35150631.92", 66814, "10", "10", "0"]


def test_parses_strings_to_floats() -> None:
    session = FakeSession([FakeResponse(200, [ROW])])
    provider = BinanceProvider(session=session)
    candles = provider.fetch_klines("btcusdt", "1h", start_ms=0, limit=5)
    assert len(candles) == 1
    candle = candles[0]
    assert isinstance(candle.open, float) and candle.open == pytest.approx(84232.86)
    assert candle.symbol == "BTCUSDT"
    assert session.requests[0]["params"]["limit"] == 5


def test_retries_429_and_honours_retry_after() -> None:
    slept: list[float] = []
    session = FakeSession([
        FakeResponse(429, headers={"Retry-After": "7"}, text="rate limited"),
        FakeResponse(200, [ROW]),
    ])
    provider = BinanceProvider(session=session, sleep=slept.append)
    candles = provider.fetch_klines("BTCUSDT", "1h")
    assert len(candles) == 1
    assert slept and slept[0] >= 7.0  # Retry-After respected


def test_retries_5xx_with_increasing_backoff() -> None:
    slept: list[float] = []
    session = FakeSession([
        FakeResponse(500, text="server error"),
        FakeResponse(502, text="bad gateway"),
        FakeResponse(200, [ROW]),
    ])
    provider = BinanceProvider(session=session, sleep=slept.append, backoff_s=1.0)
    provider.fetch_klines("BTCUSDT", "1h")
    assert slept == [1.0, 2.0]


def test_gives_up_after_max_attempts() -> None:
    session = FakeSession([FakeResponse(500, text="boom")] * 3)
    provider = BinanceProvider(session=session, max_attempts=3, sleep=lambda s: None)
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.fetch_klines("BTCUSDT", "1h")


def test_non_retryable_error_raises_immediately() -> None:
    session = FakeSession([FakeResponse(400, text="invalid symbol")])
    provider = BinanceProvider(session=session, sleep=lambda s: None)
    with pytest.raises(ProviderError, match="HTTP 400"):
        provider.fetch_klines("NOPE", "1h")
    assert len(session.requests) == 1


def test_input_validation() -> None:
    provider = BinanceProvider(session=FakeSession([]))
    with pytest.raises(ValueError):
        provider.fetch_klines("", "1h")
    with pytest.raises(ValueError):
        provider.fetch_klines("BTCUSDT", "5m")
    with pytest.raises(ValueError):
        provider.fetch_klines("BTCUSDT", "1h", limit=MAX_KLINES_PER_REQUEST + 1)
    with pytest.raises(ValueError):
        provider.fetch_klines("BTCUSDT", "1h", start_ms=10, end_ms=5)


def test_malformed_row_rejected() -> None:
    # 9 fields only -> below the 11-field kline row shape
    bad = [1, "100", "110", "90", "105", "1", 2, "10", 1]
    session = FakeSession([FakeResponse(200, [bad])])
    provider = BinanceProvider(session=session)
    with pytest.raises(ProviderError, match="malformed"):
        provider.fetch_klines("BTCUSDT", "1h")


def test_inconsistent_row_rejected_as_provider_error() -> None:
    full_row = [1, "100", "90", "80", "95", "1", 2, "10", 1, "0", "0"]  # high < low
    session = FakeSession([FakeResponse(200, [full_row])])
    provider = BinanceProvider(session=session)
    with pytest.raises(ProviderError, match="invalid candle"):
        provider.fetch_klines("BTCUSDT", "1h")


def test_network_error_is_wrapped_as_provider_error() -> None:
    session = FakeSession([requests.ConnectionError("dns failure")] * 3)
    provider = BinanceProvider(session=session, max_attempts=3, sleep=lambda s: None)
    with pytest.raises(ProviderError, match="network error"):
        provider.fetch_klines("BTCUSDT", "1h")
