"""Market data provider with caching."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.config import settings
from app.market.okx_client import get_okx_client
from app.models import InstrumentType


INST_TYPE_MAP = {
    InstrumentType.SPOT: "SPOT",
    InstrumentType.SWAP: "SWAP",
    InstrumentType.FUTURES: "FUTURES",
}

BAR_MAP = {
    "scalp": "5m",
    "mid": "10m",
    "swing": "1H",
    "hour": "1H",
    "5m": "5m",
    "10m": "10m",
    "1H": "1H",
}

BAR_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1H": 3600,
    "4H": 14400,
    "1D": 86400,
}

CANDLE_CACHE_DIR = settings.data_dir / "backtest_candles"


class MarketDataProvider:
    def __init__(self) -> None:
        self._ticker_cache: dict[str, tuple[float, list[dict]]] = {}
        self._single_ticker_cache: dict[str, tuple[float, dict[str, Any]]] = {}
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
        now = time.time()
        cached = self._single_ticker_cache.get(inst_id)
        if cached and now - cached[0] < 0.5:
            return cached[1]
        client = get_okx_client()
        data = await asyncio.to_thread(client.get_ticker, inst_id)
        if data:
            self._single_ticker_cache[inst_id] = (now, data)
        return data

    async def prices_for(self, inst_ids: list[str]) -> dict[str, float]:
        unique = [x for x in dict.fromkeys(inst_ids) if x]
        if not unique:
            return {}
        rows = await asyncio.gather(*(self.ticker(inst_id) for inst_id in unique), return_exceptions=True)
        out: dict[str, float] = {}
        for inst_id, row in zip(unique, rows):
            if isinstance(row, Exception) or not row:
                continue
            try:
                out[inst_id] = float(row.get("last", 0))
            except (TypeError, ValueError):
                continue
        return out

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

    def _cache_path(self, inst_id: str, bar: str) -> Path:
        safe = inst_id.replace("/", "_").replace(":", "_")
        return CANDLE_CACHE_DIR / f"{safe}_{bar}.json"

    def _read_cached_candles(self, inst_id: str, bar: str) -> list[list[str]]:
        path = self._cache_path(inst_id, bar)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _write_cached_candles(self, inst_id: str, bar: str, candles: list[list[str]]) -> None:
        CANDLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(inst_id, bar)
        path.write_text(json.dumps(candles, ensure_ascii=False), encoding="utf-8")

    async def candles_months(
        self,
        inst_id: str,
        strategy: str = "scalp",
        months: int = 3,
        max_pages: int = 620,
    ) -> list[list[str]]:
        bar = BAR_MAP.get(strategy, "5m")
        months = max(3, min(6, int(months or 3)))
        seconds = BAR_SECONDS.get(bar, 300)
        target_count = int(months * 30 * 24 * 3600 / seconds)
        target_count = max(80, target_count)

        cached = self._read_cached_candles(inst_id, bar)
        if cached:
            cached = self._dedupe_sort(cached)
            cutoff_ms = int((time.time() - months * 30 * 24 * 3600) * 1000)
            cached = [c for c in cached if c and int(float(c[0])) >= cutoff_ms]
            if len(cached) >= target_count * 0.9:
                return cached[-target_count:]

        client = get_okx_client()
        rows: list[list[str]] = []
        after = ""
        page_limit = 100
        target_pages = min(max_pages, int(target_count / page_limit) + 12)
        for _ in range(target_pages):
            page = await asyncio.to_thread(
                client.get_history_candles,
                inst_id,
                bar,
                page_limit,
                "",
                after,
            )
            if not page:
                if not rows:
                    page = await asyncio.to_thread(client.get_candles, inst_id, bar, page_limit)
                if not page:
                    break
            rows.extend(page)
            rows = self._dedupe_sort(rows)
            if len(rows) >= target_count:
                break
            oldest = rows[0][0] if rows and rows[0] else ""
            if not oldest or oldest == after:
                break
            after = str(oldest)
            await asyncio.sleep(0.04)

        merged = self._dedupe_sort(cached + rows)
        if merged:
            cutoff_ms = int((time.time() - months * 30 * 24 * 3600) * 1000)
            merged = [c for c in merged if c and int(float(c[0])) >= cutoff_ms]
            self._write_cached_candles(inst_id, bar, merged)
        return merged[-target_count:]

    def _dedupe_sort(self, candles: list[list[str]]) -> list[list[str]]:
        by_ts: dict[int, list[str]] = {}
        for row in candles:
            if not row:
                continue
            try:
                ts = int(float(row[0]))
            except (TypeError, ValueError):
                continue
            by_ts[ts] = row
        return [by_ts[k] for k in sorted(by_ts)]

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
