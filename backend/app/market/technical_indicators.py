"""Shared technical indicators for live analysis and backtests.

All functions accept plain sequences and return same-length Python lists. Missing
or unstable early values are filled with neutral values instead of NaN/inf so the
trading engine can use them safely in real time.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def _arr(values: Sequence[float]) -> np.ndarray:
    out = np.asarray([float(v) for v in values], dtype=float)
    if out.size == 0:
        return out
    out[~np.isfinite(out)] = 0.0
    return out


def _rolling_mean(values: np.ndarray, period: int) -> np.ndarray:
    n = len(values)
    if n == 0:
        return values.astype(float)
    period = max(1, int(period))
    out = np.empty(n, dtype=float)
    csum = np.cumsum(values, dtype=float)
    for i in range(n):
        start = max(0, i - period + 1)
        total = csum[i] - (csum[start - 1] if start > 0 else 0.0)
        out[i] = total / (i - start + 1)
    return out


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    n = len(values)
    if n == 0:
        return values.astype(float)
    period = max(1, int(period))
    alpha = 2.0 / (period + 1.0)
    out = np.empty(n, dtype=float)
    out[0] = values[0]
    for i in range(1, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _safe_list(values: np.ndarray, fallback: float = 0.0) -> list[float]:
    clean = np.asarray(values, dtype=float)
    clean[~np.isfinite(clean)] = fallback
    return [float(v) for v in clean]


def bollinger_bands(
    closes: Sequence[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> dict[str, list[float]]:
    c = _arr(closes)
    n = len(c)
    if n == 0:
        return {"upper": [], "middle": [], "lower": []}
    period = max(1, int(period))
    mid = _rolling_mean(c, period)
    std = np.empty(n, dtype=float)
    for i in range(n):
        start = max(0, i - period + 1)
        std[i] = float(np.std(c[start : i + 1]))
    upper = mid + std * float(std_dev)
    lower = mid - std * float(std_dev)
    return {
        "upper": _safe_list(upper, float(c[-1])),
        "middle": _safe_list(mid, float(c[-1])),
        "lower": _safe_list(lower, float(c[-1])),
    }


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> dict[str, list[float]]:
    h, l, c = _arr(highs), _arr(lows), _arr(closes)
    n = min(len(h), len(l), len(c))
    if n == 0:
        return {"k": [], "d": []}
    h, l, c = h[-n:], l[-n:], c[-n:]
    k_period = max(1, int(k_period))
    k = np.empty(n, dtype=float)
    for i in range(n):
        start = max(0, i - k_period + 1)
        hi = float(np.max(h[start : i + 1]))
        lo = float(np.min(l[start : i + 1]))
        span = hi - lo
        k[i] = 50.0 if span <= 0 else max(0.0, min(100.0, (c[i] - lo) / span * 100.0))
    d = _rolling_mean(k, max(1, int(d_period)))
    return {"k": _safe_list(k, 50.0), "d": _safe_list(d, 50.0)}


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float]:
    h, l, c = _arr(highs), _arr(lows), _arr(closes)
    n = min(len(h), len(l), len(c))
    if n == 0:
        return []
    h, l, c = h[-n:], l[-n:], c[-n:]
    tr = np.empty(n, dtype=float)
    tr[0] = max(0.0, h[0] - l[0])
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]), 0.0)
    return _safe_list(_ema(tr, max(1, int(period))), float(tr[-1]))


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> dict[str, list[float]]:
    h, l, c = _arr(highs), _arr(lows), _arr(closes)
    n = min(len(h), len(l), len(c))
    if n == 0:
        return {"adx": [], "plus_di": [], "minus_di": []}
    h, l, c = h[-n:], l[-n:], c[-n:]
    period = max(1, int(period))
    plus_dm = np.zeros(n, dtype=float)
    minus_dm = np.zeros(n, dtype=float)
    tr = np.zeros(n, dtype=float)
    for i in range(1, n):
        up = h[i] - h[i - 1]
        down = l[i - 1] - l[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]), 0.0)
    tr[0] = max(0.0, h[0] - l[0])
    atr_s = _ema(tr, period)
    plus_s = _ema(plus_dm, period)
    minus_s = _ema(minus_dm, period)
    denom = np.where(atr_s <= 1e-12, 1e-12, atr_s)
    plus_di = 100.0 * plus_s / denom
    minus_di = 100.0 * minus_s / denom
    di_sum = plus_di + minus_di
    dx = np.zeros(n, dtype=float)
    np.divide(
        100.0 * np.abs(plus_di - minus_di),
        di_sum,
        out=dx,
        where=di_sum > 1e-12,
    )
    adx_line = _ema(dx, period)
    # Early ADX is noisy. Neutralize the warmup section.
    warmup = min(n, period)
    adx_line[:warmup] = np.maximum(adx_line[:warmup], 20.0)
    return {
        "adx": _safe_list(adx_line, 20.0),
        "plus_di": _safe_list(plus_di, 0.0),
        "minus_di": _safe_list(minus_di, 0.0),
    }


def supertrend(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    atr_period: int = 10,
    atr_mult: float = 3.0,
) -> dict[str, list[float] | list[int]]:
    h, l, c = _arr(highs), _arr(lows), _arr(closes)
    n = min(len(h), len(l), len(c))
    if n == 0:
        return {"supertrend": [], "direction": [], "upper_band": [], "lower_band": []}
    h, l, c = h[-n:], l[-n:], c[-n:]
    atr_values = np.asarray(atr(h, l, c, atr_period), dtype=float)
    hl2 = (h + l) / 2.0
    basic_upper = hl2 + float(atr_mult) * atr_values
    basic_lower = hl2 - float(atr_mult) * atr_values
    final_upper = np.copy(basic_upper)
    final_lower = np.copy(basic_lower)
    direction = np.ones(n, dtype=int)
    line = np.copy(basic_lower)
    for i in range(1, n):
        if basic_upper[i] < final_upper[i - 1] or c[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]
        if basic_lower[i] > final_lower[i - 1] or c[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        if c[i] > final_upper[i - 1]:
            direction[i] = 1
        elif c[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
    line[0] = final_lower[0] if direction[0] == 1 else final_upper[0]
    return {
        "supertrend": _safe_list(line, float(c[-1])),
        "direction": [int(v) for v in direction],
        "upper_band": _safe_list(final_upper, float(c[-1])),
        "lower_band": _safe_list(final_lower, float(c[-1])),
    }


def indicator_snapshot(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float] | None = None,
) -> dict[str, float | int | str]:
    """Compact latest-state snapshot used for scoring and UI reasons."""
    h, l, c = _arr(highs), _arr(lows), _arr(closes)
    n = min(len(h), len(l), len(c))
    if n == 0:
        return {}
    h, l, c = h[-n:], l[-n:], c[-n:]
    st = supertrend(h, l, c)
    ax = adx(h, l, c)
    sto = stochastic(h, l, c)
    bb = bollinger_bands(c)
    atr_values = atr(h, l, c)
    v = _arr(volumes or [])
    vol_ratio = 1.0
    if len(v) >= 2:
        recent = v[-20:] if len(v) >= 20 else v
        avg = float(np.mean(recent[:-1])) if len(recent) > 1 else float(np.mean(recent))
        vol_ratio = float(recent[-1] / avg) if avg > 0 else 1.0
    last = float(c[-1])
    upper = float(bb["upper"][-1])
    lower = float(bb["lower"][-1])
    width = max(upper - lower, last * 1e-9)
    bb_pos = max(0.0, min(1.0, (last - lower) / width))
    return {
        "adx": float(ax["adx"][-1]),
        "plus_di": float(ax["plus_di"][-1]),
        "minus_di": float(ax["minus_di"][-1]),
        "supertrend_direction": int(st["direction"][-1]),
        "supertrend_line": float(st["supertrend"][-1]),
        "stoch_k": float(sto["k"][-1]),
        "stoch_d": float(sto["d"][-1]),
        "atr": float(atr_values[-1]),
        "atr_pct": float(atr_values[-1] / last * 100.0) if last > 0 else 0.0,
        "bb_pos": float(bb_pos),
        "vol_ratio": float(vol_ratio if math.isfinite(vol_ratio) else 1.0),
    }
