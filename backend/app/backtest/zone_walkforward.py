"""Walk-forward validation for ATR/structure zone predictions."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.backtest.models import BacktestZoneWalkForward


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return values.astype(float)
    alpha = 2 / (period + 1)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return float(np.mean(trs[-period:])) if trs else 0.0


def _macd_hist(closes: np.ndarray) -> np.ndarray:
    if len(closes) < 35:
        return np.zeros(len(closes), dtype=float)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd = ema12 - ema26
    sig = _ema(macd, 9)
    return macd - sig


def _parse(candles: list[list]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    try:
        opens = np.array([float(c[1]) for c in candles], dtype=float)
        highs = np.array([float(c[2]) for c in candles], dtype=float)
        lows = np.array([float(c[3]) for c in candles], dtype=float)
        closes = np.array([float(c[4]) for c in candles], dtype=float)
    except (TypeError, ValueError, IndexError):
        return None
    if len(closes) < 120:
        return None
    return opens, highs, lows, closes


def _predict_zone(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    idx: int,
    lookback: int,
) -> dict[str, Any] | None:
    start = idx - lookback
    if start < 1:
        return None
    h = highs[start:idx]
    l = lows[start:idx]
    c = closes[start:idx]
    atr = _atr(h, l, c)
    if atr <= 0 or c[-1] <= 0:
        return None

    ema20 = _ema(c, 20)
    ema50 = _ema(c, 50)
    hist = _macd_hist(c)
    if len(ema50) < 30 or len(hist) < 5:
        return None

    resistance = float(np.max(h[-30:]))
    support = float(np.min(l[-30:]))
    width_atr = (resistance - support) / atr if atr > 0 else math.inf
    slope = (ema20[-1] - ema20[-12]) / atr
    macro = (ema50[-1] - ema50[-30]) / atr
    macd_up = hist[-1] > hist[-2] > hist[-3]
    macd_down = hist[-1] < hist[-2] < hist[-3]
    price = float(c[-1])
    near_res = resistance - price <= atr * 0.45
    near_sup = price - support <= atr * 0.45

    direction = "none"
    reason = "no edge"
    if width_atr <= 5.5 and near_res and slope > 0.12 and macro > -0.35 and macd_up:
        direction = "long"
        reason = "range resistance breakout"
    elif width_atr <= 5.5 and near_sup and slope < -0.12 and macro < 0.35 and macd_down:
        direction = "short"
        reason = "range support breakdown"
    elif slope > 0.35 and macro > 0 and price > ema20[-1] > ema50[-1] and macd_up:
        direction = "long"
        reason = "trend continuation"
    elif slope < -0.35 and macro < 0 and price < ema20[-1] < ema50[-1] and macd_down:
        direction = "short"
        reason = "trend continuation"

    if direction == "none":
        return None

    return {
        "direction": direction,
        "reason": reason,
        "entry": price,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "width_atr": width_atr,
        "slope_atr": slope,
        "macro_atr": macro,
    }


def _score_forward(
    pred: dict[str, Any],
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    idx: int,
    horizon: int,
) -> dict[str, Any]:
    entry = float(pred["entry"])
    atr = float(pred["atr"])
    future_h = highs[idx : idx + horizon]
    future_l = lows[idx : idx + horizon]
    future_c = closes[idx : idx + horizon]
    if len(future_c) == 0 or entry <= 0 or atr <= 0:
        return {"hit": False, "false_break": False, "forward_r": 0.0}

    if pred["direction"] == "long":
        max_r = (float(np.max(future_h)) - entry) / atr
        min_r = (float(np.min(future_l)) - entry) / atr
        close_r = (float(future_c[-1]) - entry) / atr
        hit = max_r >= 1.0 and min_r > -0.8
        false_break = min_r <= -1.0 and max_r < 1.0
        forward_r = max(max_r, close_r)
    else:
        max_r = (entry - float(np.min(future_l))) / atr
        adverse_r = (float(np.max(future_h)) - entry) / atr
        close_r = (entry - float(future_c[-1])) / atr
        hit = max_r >= 1.0 and adverse_r < 0.8
        false_break = adverse_r >= 1.0 and max_r < 1.0
        forward_r = max(max_r, close_r)
    return {
        "hit": bool(hit),
        "false_break": bool(false_break),
        "forward_r": round(float(forward_r), 3),
    }


def evaluate_zone_walkforward(
    symbol_candles: dict[str, list[list]],
    lookback: int = 80,
    horizon: int = 12,
    step: int = 3,
    max_details: int = 40,
) -> BacktestZoneWalkForward:
    rows: list[dict[str, Any]] = []
    symbol_count = 0
    for inst_id, candles in symbol_candles.items():
        parsed = _parse(candles)
        if parsed is None:
            continue
        _, highs, lows, closes = parsed
        symbol_count += 1
        end = len(closes) - horizon
        for idx in range(lookback, end, step):
            pred = _predict_zone(highs, lows, closes, idx, lookback)
            if not pred:
                continue
            scored = _score_forward(pred, highs, lows, closes, idx, horizon)
            rows.append({
                "inst_id": inst_id,
                "bar": idx,
                "direction": pred["direction"],
                "reason": pred["reason"],
                "entry": round(float(pred["entry"]), 10),
                "atr_pct": round(float(pred["atr"] / pred["entry"] * 100), 3) if pred["entry"] else 0.0,
                "support": round(float(pred["support"]), 10),
                "resistance": round(float(pred["resistance"]), 10),
                "width_atr": round(float(pred["width_atr"]), 2),
                "forward_r": scored["forward_r"],
                "hit": scored["hit"],
                "false_break": scored["false_break"],
            })

    samples = len(rows)
    if samples == 0:
        return BacktestZoneWalkForward(symbols=symbol_count)

    wins = [r for r in rows if r["hit"]]
    false_breaks = [r for r in rows if r["false_break"]]
    longs = [r for r in rows if r["direction"] == "long"]
    shorts = [r for r in rows if r["direction"] == "short"]
    long_wins = [r for r in longs if r["hit"]]
    short_wins = [r for r in shorts if r["hit"]]

    def pct(n: int, d: int) -> float:
        return round(n / d * 100, 1) if d else 0.0

    ranked = sorted(rows, key=lambda r: (not r["hit"], -abs(float(r["forward_r"]))))[:max_details]
    return BacktestZoneWalkForward(
        symbols=symbol_count,
        samples=samples,
        accuracy_pct=pct(len(wins), samples),
        long_accuracy_pct=pct(len(long_wins), len(longs)),
        short_accuracy_pct=pct(len(short_wins), len(shorts)),
        avg_forward_r=round(float(np.mean([r["forward_r"] for r in rows])), 3),
        breakout_success_pct=pct(len(wins), samples),
        false_break_pct=pct(len(false_breaks), samples),
        details=ranked,
    )
