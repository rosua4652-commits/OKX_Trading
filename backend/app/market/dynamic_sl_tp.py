"""Chart-based dynamic SL/TP — ATR + swing structure, per strategy."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.config import settings
from app.market.data_provider import market
from app.models import AppConfig, PositionSide, StrategyMode
from app.strategy_utils import sl_tp_pcts


@dataclass
class DynamicSlTpPlan:
    stop_loss: float
    take_profit: float
    sl_pct: float
    tp_pct: float
    method: str
    atr_pct: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _parse_ohlc(candles: list[list[str]]) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if len(candles) < 20:
        return None
    try:
        highs = np.array([float(c[2]) for c in candles])
        lows = np.array([float(c[3]) for c in candles])
        closes = np.array([float(c[4]) for c in candles])
        return highs, lows, closes
    except (TypeError, ValueError, IndexError):
        return None


def _atr_pct(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    tr_list: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
    if not tr_list:
        return 1.0
    window = tr_list[-period:] if len(tr_list) >= period else tr_list
    atr = float(np.mean(window))
    last = float(closes[-1])
    if last <= 0:
        return 1.0
    return atr / last * 100.0


def _plan_from_ohlc(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    entry: float,
    side: PositionSide,
    strategy: StrategyMode,
    config: AppConfig,
) -> DynamicSlTpPlan:
    atr_p = _atr_pct(highs, lows, closes)
    lookback = 24 if strategy == StrategyMode.SCALP else 48
    lookback = min(lookback, len(closes))
    recent_high = float(np.max(highs[-lookback:]))
    recent_low = float(np.min(lows[-lookback:]))

    fallback_sl, fallback_tp = sl_tp_pcts(config, strategy)
    if strategy == StrategyMode.SWING:
        min_sl, max_sl = 2.5, 14.0
        min_tp, max_tp = 5.0, 22.0
        sl_atr_mult, rr_base = 2.2, 2.8
    else:
        min_sl, max_sl = 0.7, 5.0
        min_tp, max_tp = 1.0, 8.0
        sl_atr_mult, rr_base = 1.4, 1.9

    # 추세 강도: 최근 종가 vs EMA
    ema = float(np.mean(closes[-min(20, len(closes)):]))
    trend_strength = abs(closes[-1] - ema) / ema * 100 if ema > 0 else 0
    rr = _clamp(rr_base + trend_strength * 0.08, rr_base, rr_base + 1.2)

    if side == PositionSide.LONG:
        struct_sl = (entry - recent_low) / entry * 100.0 if entry > 0 else min_sl
        struct_tp = (recent_high - entry) / entry * 100.0 if entry > 0 else min_tp
        sl_pct = _clamp(max(atr_p * sl_atr_mult, struct_sl * 0.92), min_sl, max_sl)
        tp_from_rr = sl_pct * rr
        tp_from_struct = struct_tp * 0.88
        tp_pct = _clamp(max(tp_from_rr, tp_from_struct, atr_p * sl_atr_mult * rr), min_tp, max_tp)
        sl_price = entry * (1 - sl_pct / 100)
        tp_price = entry * (1 + tp_pct / 100)
        method = f"ATR {atr_p:.1f}%·저점 {struct_sl:.1f}%"
    else:
        struct_sl = (recent_high - entry) / entry * 100.0 if entry > 0 else min_sl
        struct_tp = (entry - recent_low) / entry * 100.0 if entry > 0 else min_tp
        sl_pct = _clamp(max(atr_p * sl_atr_mult, struct_sl * 0.92), min_sl, max_sl)
        tp_from_rr = sl_pct * rr
        tp_from_struct = struct_tp * 0.88
        tp_pct = _clamp(max(tp_from_rr, tp_from_struct, atr_p * sl_atr_mult * rr), min_tp, max_tp)
        sl_price = entry * (1 + sl_pct / 100)
        tp_price = entry * (1 - tp_pct / 100)
        method = f"ATR {atr_p:.1f}%·고점 {struct_sl:.1f}%"

    if sl_pct <= 0 or tp_pct <= 0:
        sl_pct, tp_pct = fallback_sl, fallback_tp
        if side == PositionSide.LONG:
            sl_price = entry * (1 - sl_pct / 100)
            tp_price = entry * (1 + tp_pct / 100)
        else:
            sl_price = entry * (1 + sl_pct / 100)
            tp_price = entry * (1 - tp_pct / 100)
        method = "기본값"

    label = "장타" if strategy == StrategyMode.SWING else "단타"
    return DynamicSlTpPlan(
        stop_loss=round(sl_price, 12),
        take_profit=round(tp_price, 12),
        sl_pct=round(sl_pct, 2),
        tp_pct=round(tp_pct, 2),
        method=f"{label} {method}",
        atr_pct=round(atr_p, 2),
    )


def plan_from_candles(
    candles: list[list[str]],
    entry: float,
    side: PositionSide,
    strategy: StrategyMode,
    config: AppConfig,
) -> DynamicSlTpPlan:
    parsed = _parse_ohlc(candles)
    if not parsed:
        fb_sl, fb_tp = sl_tp_pcts(config, strategy)
        if side == PositionSide.LONG:
            return DynamicSlTpPlan(
                entry * (1 - fb_sl / 100),
                entry * (1 + fb_tp / 100),
                fb_sl,
                fb_tp,
                "캔들부족·기본",
            )
        return DynamicSlTpPlan(
            entry * (1 + fb_sl / 100),
            entry * (1 - fb_tp / 100),
            fb_sl,
            fb_tp,
            "캔들부족·기본",
        )
    return _plan_from_ohlc(*parsed, entry, side, strategy, config)


async def compute_dynamic_sl_tp(
    inst_id: str,
    entry: float,
    side: PositionSide,
    strategy: StrategyMode,
    config: AppConfig | None = None,
) -> DynamicSlTpPlan:
    cfg = config or AppConfig()
    if strategy == StrategyMode.BOTH:
        strategy = StrategyMode.SCALP

    from app.backtest.symbol_sl_tp import plan_prices, resolve_entry_sl_tp

    bt = resolve_entry_sl_tp(inst_id, cfg, strategy)
    if bt is not None:
        sl_pct, tp_pct, method = bt
        sl_p, tp_p = plan_prices(entry, side, sl_pct, tp_pct)
        return DynamicSlTpPlan(
            stop_loss=round(sl_p, 12),
            take_profit=round(tp_p, 12),
            sl_pct=round(sl_pct, 2),
            tp_pct=round(tp_pct, 2),
            method=method,
        )

    strat_key = "swing" if strategy == StrategyMode.SWING else "scalp"
    limit = 80 if strategy == StrategyMode.SWING else 60
    candles = await market.candles(inst_id, strat_key, limit)
    return plan_from_candles(candles, entry, side, strategy, cfg)
