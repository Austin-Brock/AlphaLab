"""Alpaca Market Data API v2 client (https://docs.alpaca.markets/reference/stocklatesttrades)."""

import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx2

from app.market_data.provider import Bar, MarketDataUnavailableError, Quote, Timeframe

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AlpacaMarketDataProvider:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = "https://data.alpaca.markets",
        feed: str = "iex",
        max_attempts: int = 3,
        client: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.source = f"alpaca-{feed}"
        self.feed = feed
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.client = client or httpx2.Client(timeout=10.0)
        self.base_url = base_url.rstrip("/")
        self.headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}

    def get_latest_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        data = self._get(
            "/v2/stocks/trades/latest", {"symbols": ",".join(symbols), "feed": self.feed}
        )
        return {
            symbol: Quote(
                symbol=symbol, price=Decimal(trade["p"]), price_time=_parse_time(trade["t"])
            )
            for symbol, trade in data.get("trades", {}).items()
        }

    def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        params: dict[str, Any] = {
            "symbols": symbol,
            "timeframe": timeframe.value,
            "start": start.isoformat(),
            "end": end.isoformat(),
            # Split-adjusted so prices are comparable across a split.
            "adjustment": "split",
            "feed": self.feed,
            "limit": 10000,
        }
        bars: list[Bar] = []
        while True:
            data = self._get("/v2/stocks/bars", params)
            bars.extend(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=_parse_time(raw["t"]),
                    open=Decimal(raw["o"]),
                    high=Decimal(raw["h"]),
                    low=Decimal(raw["l"]),
                    close=Decimal(raw["c"]),
                    volume=int(raw["v"]),
                )
                for raw in (data.get("bars") or {}).get(symbol, [])
            )
            if not data.get("next_page_token"):
                return bars
            params["page_token"] = data["next_page_token"]

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with retries on rate limits, server errors, and network failures."""
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.get(
                    self.base_url + path, params=params, headers=self.headers
                )
            except httpx2.TransportError as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    # Parse numbers as Decimal so prices never pass through float.
                    return response.json(parse_float=Decimal)
                last_error = f"HTTP {response.status_code}: {_error_text(response)}"
                if response.status_code not in RETRYABLE_STATUS:
                    break
            if attempt < self.max_attempts:
                self.sleep(0.5 * 2 ** (attempt - 1))
        raise MarketDataUnavailableError(f"Alpaca request to {path} failed ({last_error})")


def _error_text(response: httpx2.Response) -> str:
    """A short single-line error message; Alpaca sometimes returns an HTML error page."""
    try:
        return str(response.json().get("message", response.text))[:200]
    except ValueError:
        title = re.search(r"<title>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
        text = title.group(1) if title else re.sub(r"<[^>]+>", " ", response.text)
        return " ".join(text.split())[:200]


def _parse_time(value: str) -> datetime:
    # Alpaca returns RFC 3339 with up to nanosecond precision; Python accepts microseconds.
    if "." in value:
        head, frac = value.split(".", 1)
        digits = "".join(c for c in frac if c.isdigit())
        value = f"{head}.{digits[:6]}{frac[len(digits) :]}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
