"""Market scanner — finds trading candidates."""

from __future__ import annotations

from app.config import settings
from app.market.data_provider import market
from app.models import CoinCandidate, InstrumentType, StrategyMode


def _parse_float(val: str | float | None, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _volume_usdt(ticker: dict) -> float:
    vol_ccy = _parse_float(ticker.get("volCcy24h"))
    if vol_ccy > 0:
        return vol_ccy
    last = _parse_float(ticker.get("last"))
    vol = _parse_float(ticker.get("vol24h"))
    return vol * last if last > 0 else 0.0


def _change_pct(ticker: dict) -> float:
    open24 = _parse_float(ticker.get("open24h"))
    last = _parse_float(ticker.get("last"))
    if open24 <= 0:
        return 0.0
    return (last - open24) / open24 * 100


async def scan_market(
    instrument: InstrumentType = InstrumentType.SWAP,
    strategy: StrategyMode = StrategyMode.SCALP,
    limit: int = 30,
    min_volume: float | None = None,
) -> list[CoinCandidate]:
    tickers = await market.tickers(instrument)
    min_vol = min_volume or (
        settings.scalp_min_quote_volume_usdt
        if strategy == StrategyMode.SCALP
        else settings.min_quote_volume_usdt
    )
    min_change = (
        settings.scalp_min_abs_change_24h_pct
        if strategy == StrategyMode.SCALP
        else 0.5
    )

    candidates: list[CoinCandidate] = []
    for t in tickers:
        inst_id = t.get("instId", "")
        if not inst_id or "USDT" not in inst_id:
            continue
        if instrument == InstrumentType.SPOT and "-SWAP" in inst_id:
            continue
        if instrument == InstrumentType.SWAP and "-SWAP" not in inst_id:
            continue

        vol = _volume_usdt(t)
        if vol < min_vol:
            continue

        change = _change_pct(t)
        if abs(change) < min_change:
            continue

        last = _parse_float(t.get("last"))
        if last <= 0:
            continue

        candidates.append(
            CoinCandidate(
                inst_id=inst_id,
                last_price=last,
                change_24h_pct=round(change, 2),
                volume_24h_usdt=round(vol, 0),
            )
        )

    candidates.sort(key=lambda c: c.volume_24h_usdt, reverse=True)
    return candidates[:limit]


async def top_symbols(
    instrument: InstrumentType = InstrumentType.SWAP,
    limit: int = 20,
) -> list[str]:
    cands = await scan_market(instrument, limit=limit, min_volume=settings.min_quote_volume_usdt)
    return [c.inst_id for c in cands]
