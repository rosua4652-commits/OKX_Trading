"""Chart and liquidity based dynamic SL/TP."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.market.data_provider import market
from app.models import AppConfig, InstrumentType, PositionSide, StrategyMode
from app.sl_tp_utils import (
    enforce_wide_rr_sl_tp,
    leverage_safe_sl_pct,
    pnl_pct_to_price_pct,
    price_pct_to_pnl_pct,
)
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


def _float(v: object, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _volume_usdt(ticker: dict | None) -> float:
    if not ticker:
        return 0.0
    vol_ccy = _float(ticker.get("volCcy24h"))
    if vol_ccy > 0:
        return vol_ccy
    last = _float(ticker.get("last"))
    vol = _float(ticker.get("vol24h"))
    return vol * last if last > 0 else 0.0


def _liquidity_sl_cap(volume_usdt: float, strategy: StrategyMode) -> float:
    """Max user-facing ROI% SL. More liquid symbols can breathe wider, capped at 12%."""
    base = 7.0 if strategy == StrategyMode.SWING else 5.0
    if volume_usdt >= 50_000_000:
        return 12.0
    if volume_usdt >= 10_000_000:
        return 9.0
    if volume_usdt >= 3_000_000:
        return max(base, 7.0)
    return base


def _leverage_safe_sl_cap(leverage: int, instrument_type: InstrumentType | str) -> float:
    """Keep stop-loss inside a conservative liquidation-risk buffer."""
    if instrument_type in (InstrumentType.SPOT, "spot"):
        return 80.0
    lev = max(1, leverage)
    max_price_move = max(0.2, (100 / lev) * 0.65)
    return max_price_move * lev


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
    volume_usdt: float = 0.0,
) -> DynamicSlTpPlan:
    atr_p = _atr_pct(highs, lows, closes)
    lookback = 24 if strategy == StrategyMode.SCALP else 48
    lookback = min(lookback, len(closes))
    recent_high = float(np.max(highs[-lookback:]))
    recent_low = float(np.min(lows[-lookback:]))

    leverage = max(1, config.leverage or 1)
    min_sl_roi = 8.0 if strategy == StrategyMode.SWING else 6.0
    max_sl_roi = min(
        _liquidity_sl_cap(volume_usdt, strategy),
        _leverage_safe_sl_cap(leverage, config.instrument_type),
    )
    min_tp_roi = 7.0 if strategy == StrategyMode.SWING else max(5.0, min_sl_roi * 1.15)
    max_tp_roi = 24.0 if strategy == StrategyMode.SWING else 10.0
    sl_atr_mult = 2.6 if strategy == StrategyMode.SWING else 2.0
    rr_base = 2.2 if strategy == StrategyMode.SWING else 1.35

    ema = float(np.mean(closes[-min(20, len(closes)):]))
    trend_strength = abs(closes[-1] - ema) / ema * 100 if ema > 0 else 0
    rr = _clamp(rr_base + trend_strength * 0.05, rr_base, rr_base + (0.8 if strategy == StrategyMode.SWING else 0.35))

    if side == PositionSide.LONG:
        struct_sl_price_pct = (entry - recent_low) / entry * 100.0 if entry > 0 else 0.0
        struct_tp_price_pct = (recent_high - entry) / entry * 100.0 if entry > 0 else 0.0
    else:
        struct_sl_price_pct = (recent_high - entry) / entry * 100.0 if entry > 0 else 0.0
        struct_tp_price_pct = (entry - recent_low) / entry * 100.0 if entry > 0 else 0.0

    raw_sl_price_pct = max(atr_p * sl_atr_mult, struct_sl_price_pct * 0.92)
    raw_tp_price_pct = max(
        raw_sl_price_pct * rr,
        struct_tp_price_pct * 0.88,
        atr_p * sl_atr_mult * rr,
    )

    sl_pct = _clamp(
        price_pct_to_pnl_pct(raw_sl_price_pct, leverage, config.instrument_type),
        min_sl_roi,
        max_sl_roi,
    )
    tp_pct = _clamp(
        price_pct_to_pnl_pct(raw_tp_price_pct, leverage, config.instrument_type),
        min_tp_roi,
        max_tp_roi,
    )
    sl_pct, tp_pct = enforce_wide_rr_sl_tp(
        sl_pct,
        tp_pct,
        leverage,
        config.instrument_type,
        strategy,
        rr=rr,
    )
    sl_price_pct = pnl_pct_to_price_pct(sl_pct, leverage, config.instrument_type)
    tp_price_pct = pnl_pct_to_price_pct(tp_pct, leverage, config.instrument_type)

    if side == PositionSide.LONG:
        sl_price = entry * (1 - sl_price_pct / 100)
        tp_price = entry * (1 + tp_price_pct / 100)
        structure_label = f"low {struct_sl_price_pct:.1f}%"
    else:
        sl_price = entry * (1 + sl_price_pct / 100)
        tp_price = entry * (1 - tp_price_pct / 100)
        structure_label = f"high {struct_sl_price_pct:.1f}%"

    label = "swing" if strategy == StrategyMode.SWING else "scalp"
    method = (
        f"{label} ATR {atr_p:.1f}% {structure_label} "
        f"liqCap {max_sl_roi:.0f}%"
    )
    return DynamicSlTpPlan(
        stop_loss=round(sl_price, 12),
        take_profit=round(tp_price, 12),
        sl_pct=round(sl_pct, 2),
        tp_pct=round(tp_pct, 2),
        method=method,
        atr_pct=round(atr_p, 2),
    )


def _fallback_plan(
    entry: float,
    side: PositionSide,
    strategy: StrategyMode,
    config: AppConfig,
) -> DynamicSlTpPlan:
    fb_sl, fb_tp = sl_tp_pcts(config, strategy)
    leverage = max(1, config.leverage or 1)
    fb_sl = leverage_safe_sl_pct(fb_sl, leverage, config.instrument_type)
    fb_sl, fb_tp = enforce_wide_rr_sl_tp(
        fb_sl,
        fb_tp,
        leverage,
        config.instrument_type,
        strategy,
        rr=1.35 if strategy == StrategyMode.SCALP else 1.8,
    )
    sl_price_pct = pnl_pct_to_price_pct(fb_sl, leverage, config.instrument_type)
    tp_price_pct = pnl_pct_to_price_pct(fb_tp, leverage, config.instrument_type)
    if side == PositionSide.LONG:
        stop_loss = entry * (1 - sl_price_pct / 100)
        take_profit = entry * (1 + tp_price_pct / 100)
    else:
        stop_loss = entry * (1 + sl_price_pct / 100)
        take_profit = entry * (1 - tp_price_pct / 100)
    return DynamicSlTpPlan(
        round(stop_loss, 12),
        round(take_profit, 12),
        fb_sl,
        fb_tp,
        "fallback default",
    )


def plan_from_candles(
    candles: list[list[str]],
    entry: float,
    side: PositionSide,
    strategy: StrategyMode,
    config: AppConfig,
    volume_usdt: float = 0.0,
) -> DynamicSlTpPlan:
    parsed = _parse_ohlc(candles)
    if not parsed:
        return _fallback_plan(entry, side, strategy, config)
    return _plan_from_ohlc(*parsed, entry, side, strategy, config, volume_usdt)


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

    if not cfg.backtest_auto_sl_tp:
        return _fallback_plan(entry, side, strategy, cfg)

    bt = resolve_entry_sl_tp(inst_id, cfg, strategy)
    if bt is not None:
        sl_pct, tp_pct, method = bt
        sl_pct, tp_pct = enforce_wide_rr_sl_tp(
            sl_pct,
            tp_pct,
            cfg.leverage,
            cfg.instrument_type,
            strategy,
            rr=1.35 if strategy == StrategyMode.SCALP else 1.8,
        )
        sl_p, tp_p = plan_prices(entry, side, sl_pct, tp_pct, cfg.leverage)
        return DynamicSlTpPlan(
            stop_loss=round(sl_p, 12),
            take_profit=round(tp_p, 12),
            sl_pct=round(sl_pct, 2),
            tp_pct=round(tp_pct, 2),
            method=method,
        )

    strat_key = "swing" if strategy == StrategyMode.SWING else "scalp"
    limit = 80 if strategy == StrategyMode.SWING else 60
    ticker = await market.ticker(inst_id)
    candles = await market.candles(inst_id, strat_key, limit)
    return plan_from_candles(candles, entry, side, strategy, cfg, _volume_usdt(ticker))
