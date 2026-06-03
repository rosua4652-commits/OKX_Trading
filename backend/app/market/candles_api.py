"""OHLC candle serialization for charts."""

from __future__ import annotations

from typing import Any

from app.market.data_provider import market


def parse_okx_candles(raw: list[list[str]]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for row in raw:
        if len(row) < 5:
            continue
        try:
            ts_ms = int(row[0])
            o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            vol = float(row[5]) if len(row) > 5 else 0.0
            out.append({
                "time": ts_ms // 1000,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            })
        except (TypeError, ValueError):
            continue
    return out


async def fetch_chart_candles(inst_id: str, strategy: str = "scalp", limit: int = 100) -> list[dict[str, Any]]:
    raw = await market.candles(inst_id, strategy, limit)
    return parse_okx_candles(raw)
