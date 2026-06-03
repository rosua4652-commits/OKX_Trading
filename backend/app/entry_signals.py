"""Shared entry side resolution (live + backtest)."""

from __future__ import annotations

from app.models import (
    AppConfig,
    CoinCandidate,
    InstrumentType,
    PositionSide,
    PositionSideMode,
)


def resolve_entry_side(config: AppConfig, cand: CoinCandidate) -> PositionSide | None:
    mode = config.position_side
    if mode == PositionSideMode.LONG:
        if cand.outlook == "short":
            return None
        return PositionSide.LONG
    if mode == PositionSideMode.SHORT:
        if config.instrument_type == InstrumentType.SPOT:
            return None
        if not config.allow_short:
            return None
        if cand.outlook == "short" or cand.short_scalp_ok or cand.short_swing_ok:
            return PositionSide.SHORT
        return None

    if config.allow_short and config.instrument_type != InstrumentType.SPOT:
        if cand.outlook == "short":
            return PositionSide.SHORT
        if cand.short_scalp_ok or cand.short_swing_ok:
            return PositionSide.SHORT
        if cand.trend == "down" and cand.rsi >= 52 and cand.change_24h_pct < -2:
            return PositionSide.SHORT
        if cand.rsi >= 65 and cand.trend in ("down", "sideways"):
            return PositionSide.SHORT

    if cand.outlook == "long" or cand.scalp_ok or cand.swing_ok:
        return PositionSide.LONG
    if cand.score >= config.min_score and cand.trend in ("strong_up", "up"):
        return PositionSide.LONG
    return None
