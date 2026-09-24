"""Candle data model and validation."""

from __future__ import annotations

from dataclasses import dataclass


class CandleValidationError(ValueError):
    """Raised when a candle's fields are internally inconsistent."""


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    interval: str
    open_time: int          # epoch milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float           # base-asset volume
    close_time: int         # epoch milliseconds (exclusive end of the candle)
    quote_volume: float
    trades: int

    def validate(self) -> None:
        """Raise CandleValidationError if this candle is not self-consistent."""
        errors: list[str] = []

        if self.high < max(self.open, self.close, self.low):
            errors.append(
                f"high={self.high} < max(open,close,low)="
                f"{max(self.open, self.close, self.low)}"
            )
        if self.low > min(self.open, self.close, self.high):
            errors.append(
                f"low={self.low} > min(open,close,high)="
                f"{min(self.open, self.close, self.high)}"
            )
        if self.volume < 0:
            errors.append(f"volume={self.volume} is negative")
        if self.quote_volume < 0:
            errors.append(f"quote_volume={self.quote_volume} is negative")
        for name in ("open", "high", "low", "close"):
            value = getattr(self, name)
            if value <= 0:
                errors.append(f"{name}={value} must be positive")
        if self.open_time >= self.close_time:
            errors.append(
                f"open_time={self.open_time} >= close_time={self.close_time}"
            )
        if self.trades < 0:
            errors.append(f"trades={self.trades} is negative")

        if errors:
            raise CandleValidationError(
                f"invalid candle {self.symbol}/{self.interval}@{self.open_time}: "
                + "; ".join(errors)
            )
