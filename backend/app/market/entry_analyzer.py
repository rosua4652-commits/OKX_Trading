"""Technical analysis for entry signals."""

from __future__ import annotations

import numpy as np

from app.market.data_provider import market
from app.models import CoinCandidate, StrategyMode


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) < period:
        return values.astype(float)
    alpha = 2 / (period + 1)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains.mean() or 1e-9
    avg_loss = losses.mean() or 1e-9
    return float(100 - (100 / (1 + avg_gain / avg_loss)))


def _macd_signal(closes: np.ndarray) -> tuple[float, str]:
    if len(closes) < 35:
        return 0.0, "neutral"
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal = _ema(macd_line, 9)
    diff = macd_line[-1] - signal[-1]
    if diff > 0 and macd_line[-1] > 0:
        return diff, "bullish"
    if diff < 0 and macd_line[-1] < 0:
        return diff, "bearish"
    return diff, "neutral"


def _analyze_closes(
    closes: np.ndarray,
    volumes: np.ndarray,
    strategy: StrategyMode,
) -> tuple[float, bool, bool, str, list[str], float, str]:
    reasons: list[str] = []
    score = 0.0

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    ema50 = _ema(closes, 50)
    rsi = _rsi(closes)
    _, macd_trend = _macd_signal(closes)

    if closes[-1] > ema12[-1] > ema26[-1] > ema50[-1]:
        score += 30 if strategy == StrategyMode.SWING else 25
        trend = "strong_up"
        reasons.append("EMA 정배열")
    elif closes[-1] > ema26[-1] and ema12[-1] > ema50[-1]:
        score += 20
        trend = "up"
        reasons.append("상승 추세")
    elif closes[-1] < ema26[-1] and ema12[-1] < ema50[-1]:
        score -= 10
        trend = "down"
        reasons.append("하락 추세")
    else:
        trend = "sideways"
        score += 10 if strategy == StrategyMode.SCALP else 5
        reasons.append("횡보")

    if strategy == StrategyMode.SCALP:
        if 40 <= rsi <= 65:
            score += 20
            reasons.append(f"RSI {rsi:.0f} 단타 적합")
        elif rsi > 75:
            score -= 15
            reasons.append(f"RSI {rsi:.0f} 과열")
        elif rsi < 30:
            score += 10
            reasons.append("과매도 반등 기대")
    else:
        if 45 <= rsi <= 60:
            score += 18
            reasons.append(f"RSI {rsi:.0f} 스윙 적합")
        elif rsi > 70:
            score -= 8
            reasons.append("과열 주의")

    if macd_trend == "bullish":
        score += 15
        reasons.append("MACD 상승")
    elif macd_trend == "bearish":
        score -= 10
        reasons.append("MACD 하락")

    if len(closes) >= 6:
        lows = [min(closes[i - 1], closes[i]) for i in range(-5, 0)]
        if all(lows[i] <= lows[i + 1] for i in range(len(lows) - 1)):
            score += 12
            reasons.append("저점 상승")

    if len(volumes) >= 10:
        vol_avg = volumes[-20:].mean() if len(volumes) >= 20 else volumes.mean()
        if volumes[-1] > vol_avg * 1.3:
            score += 10
            reasons.append("거래량 증가")

    scalp_ok = score >= 55 and trend in ("strong_up", "up", "sideways")
    swing_ok = score >= 50 and trend in ("strong_up", "up")

    if trend == "down" and rsi > 60:
        scalp_ok = False
        swing_ok = False

    outlook = "long" if score >= 50 else ("short" if score < 35 and trend == "down" else "neutral")
    return score, scalp_ok, swing_ok, outlook, reasons, rsi, trend


async def analyze_entry(
    inst_id: str,
    strategy: StrategyMode = StrategyMode.SCALP,
) -> CoinCandidate | None:
    strategy_key = "scalp" if strategy == StrategyMode.SCALP else "swing"
    candles = await market.candles(inst_id, strategy_key, limit=120)
    if len(candles) < 30:
        return None

    closes = np.array([float(c[4]) for c in candles])
    volumes = np.array([float(c[5]) for c in candles])
    ticker = await market.ticker(inst_id)
    if not ticker:
        return None

    last = float(ticker.get("last", closes[-1]))
    open24 = float(ticker.get("open24h", last))
    change = (last - open24) / open24 * 100 if open24 > 0 else 0.0
    vol = float(ticker.get("volCcy24h", 0))

    score, scalp_ok, swing_ok, outlook, reasons, rsi, trend = _analyze_closes(
        closes, volumes, strategy
    )

    return CoinCandidate(
        inst_id=inst_id,
        last_price=last,
        change_24h_pct=round(change, 2),
        volume_24h_usdt=round(vol, 0),
        score=round(score, 1),
        scalp_ok=scalp_ok,
        swing_ok=swing_ok,
        outlook=outlook,
        reasons=reasons,
        rsi=round(rsi, 1),
        trend=trend,
    )


async def analyze_batch(
    inst_ids: list[str],
    strategy: StrategyMode = StrategyMode.SCALP,
) -> list[CoinCandidate]:
    results: list[CoinCandidate] = []
    for inst_id in inst_ids:
        cand = await analyze_entry(inst_id, strategy)
        if cand:
            results.append(cand)
    results.sort(key=lambda c: c.score, reverse=True)
    return results
