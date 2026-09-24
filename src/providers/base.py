"""Abstract market data provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import Candle


class MarketDataProvider(ABC):
    """Source of historical candles for a symbol/interval pair."""

    @abstractmethod
    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Return candles with open_time in [start_ms, end_ms], oldest first.

        Implementations must return at most their documented per-request cap.
        """
        raise NotImplementedError
