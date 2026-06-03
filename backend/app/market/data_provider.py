"""Market data provider with caching."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.market.okx_client import get_okx_client
from app.models import InstrumentType


INST_TYPE_MAP = {
    InstrumentType.SPOT: "SPOT",
    InstrumentType.SWAP: "SWAP",
    InstrumentType.FUTURES: "FUTURES",
}

BAR_MAP = {
    "scalp": "5m",
    "swing": "1H",
}


class MarketDataProvider:
    def __init__(self) -> None:
        self._ticker_cache: dict[str, tuple[float, list[dict]]] = {}
        self._candle_cache: dict[str, tuple[float, list]] = {}

    def _inst_type(self, instrument: InstrumentType) -> str:
        return INST_TYPE_MAP.get(instrument, "SWAP")

    async def tickers(self, instrument: InstrumentType = InstrumentType.SWAP) -> list[dict[str, Any]]:
        key = instrument.value
        now = time.time()
        cached = self._ticker_cache.get(key)
        if cached and now - cached[0] < 15:
            return cached[1]
        client = get_okx_client()
        data = await asyncio.to_thread(client.get_tickers, self._inst_type(instrument))
        self._ticker_cache[key] = (now, data)
        return data

    async def ticker(self, inst_id: str) -> dict[str, Any] | None:
        client = get_okx_client()
        return await asyncio.to_thread(client.get_ticker, inst_id)

    async def candles(
        self,
        inst_id: str,
        strategy: str = "scalp",
        limit: int = 120,
    ) -> list[list[str]]:
        bar = BAR_MAP.get(strategy, "5m")
        cache_key = f"{inst_id}:{bar}:{limit}"
        now = time.time()
        cached = self._candle_cache.get(cache_key)
        if cached and now - cached[0] < 30:
            return cached[1]
        client = get_okx_client()
        data = await asyncio.to_thread(client.get_candles, inst_id, bar, limit)
        data = list(reversed(data))
        self._candle_cache[cache_key] = (now, data)
        return data

    async def price_map(self, instrument: InstrumentType = InstrumentType.SWAP) -> dict[str, float]:
        tickers = await self.tickers(instrument)
        out: dict[str, float] = {}
        for t in tickers:
            inst_id = t.get("instId", "")
            try:
                out[inst_id] = float(t.get("last", 0))
            except (TypeError, ValueError):
                continue
        return out


market = MarketDataProvider()
