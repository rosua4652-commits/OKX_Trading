"""Candlestick pattern rules shared by live analysis and backtests."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import InstrumentType, PositionSide
from app.sl_tp_utils import price_pct_to_pnl_pct


@dataclass(frozen=True)
class ThreeSoldiersSignal:
    interval: str
    side: PositionSide
    score_bonus: float
    entry: float
    stop_loss: float
    take_profit: float
    sl_pct: float
    tp_pct: float
    reason: str


THREE_SOLDIERS_WEIGHTS = {
    "5m": 8.0,
    "10m": 16.0,
    "1H": 24.0,
}


def _f(row: list, idx: int) -> float:
    try:
        return float(row[idx])
    except (TypeError, ValueError, IndexError):
        return 0.0


def detect_three_white_soldiers(
    candles: list[list],
    interval: str,
    leverage: int = 1,
    instrument_type: InstrumentType | str = InstrumentType.SWAP,
) -> ThreeSoldiersSignal | None:
    """Detect three increasing bullish candles.

    Rule:
    - Last three completed candles are all bullish.
    - Body size grows candle by candle.
    - Entry is the third candle close.
    - Stop is the first candle low.
    - Take-profit is 1:1 from entry to stop.
    """
    if len(candles) < 3:
        return None
    rows = candles[-3:]
    opens = [_f(r, 1) for r in rows]
    highs = [_f(r, 2) for r in rows]
    lows = [_f(r, 3) for r in rows]
    closes = [_f(r, 4) for r in rows]
    if min(opens + highs + lows + closes) <= 0:
        return None

    bodies = [c - o for o, c in zip(opens, closes)]
    if not all(b > 0 for b in bodies):
        return None
    if not (bodies[0] < bodies[1] < bodies[2]):
        return None
    if not (closes[0] < closes[1] < closes[2]):
        return None

    entry = closes[2]
    stop = lows[0]
    if stop <= 0 or stop >= entry:
        return None
    risk = entry - stop
    risk_price_pct = risk / entry * 100.0
    if risk_price_pct < 0.05:
        return None

    take_profit = entry + risk
    lev = max(1, int(leverage or 1))
    sl_pct = price_pct_to_pnl_pct(risk_price_pct, lev, instrument_type)
    tp_pct = sl_pct
    bonus = THREE_SOLDIERS_WEIGHTS.get(interval, 8.0)
    return ThreeSoldiersSignal(
        interval=interval,
        side=PositionSide.LONG,
        score_bonus=bonus,
        entry=entry,
        stop_loss=round(stop, 12),
        take_profit=round(take_profit, 12),
        sl_pct=round(sl_pct, 2),
        tp_pct=round(tp_pct, 2),
        reason=f"적삼병 {interval}: 3연속 양봉 확대, 3봉 종가 진입, 1봉 저가 SL, 1:1 TP",
    )


def detect_three_black_crows(
    candles: list[list],
    interval: str,
    leverage: int = 1,
    instrument_type: InstrumentType | str = InstrumentType.SWAP,
) -> ThreeSoldiersSignal | None:
    """Detect three increasing bearish candles, the short-side mirror pattern."""
    if len(candles) < 3:
        return None
    rows = candles[-3:]
    opens = [_f(r, 1) for r in rows]
    highs = [_f(r, 2) for r in rows]
    lows = [_f(r, 3) for r in rows]
    closes = [_f(r, 4) for r in rows]
    if min(opens + highs + lows + closes) <= 0:
        return None

    bodies = [o - c for o, c in zip(opens, closes)]
    if not all(b > 0 for b in bodies):
        return None
    if not (bodies[0] < bodies[1] < bodies[2]):
        return None
    if not (closes[0] > closes[1] > closes[2]):
        return None

    entry = closes[2]
    stop = highs[0]
    if entry <= 0 or stop <= entry:
        return None
    risk = stop - entry
    risk_price_pct = risk / entry * 100.0
    if risk_price_pct < 0.05:
        return None

    take_profit = entry - risk
    if take_profit <= 0:
        return None
    lev = max(1, int(leverage or 1))
    sl_pct = price_pct_to_pnl_pct(risk_price_pct, lev, instrument_type)
    tp_pct = sl_pct
    bonus = THREE_SOLDIERS_WEIGHTS.get(interval, 8.0)
    return ThreeSoldiersSignal(
        interval=interval,
        side=PositionSide.SHORT,
        score_bonus=bonus,
        entry=entry,
        stop_loss=round(stop, 12),
        take_profit=round(take_profit, 12),
        sl_pct=round(sl_pct, 2),
        tp_pct=round(tp_pct, 2),
        reason=f"흑삼병 {interval}: 3연속 음봉 확대, 3봉 종가 숏, 1봉 고가 SL, 1:1 TP",
    )


def best_three_candle_pattern(signals: list[ThreeSoldiersSignal | None]) -> ThreeSoldiersSignal | None:
    valid = [s for s in signals if s is not None]
    if not valid:
        return None
    return max(valid, key=lambda s: (s.score_bonus, s.sl_pct))


def best_three_white_soldiers(signals: list[ThreeSoldiersSignal | None]) -> ThreeSoldiersSignal | None:
    return best_three_candle_pattern(signals)


def resample_ohlcv(candles: list[list], group: int) -> list[list]:
    """Aggregate oldest->newest OKX candles into larger bars."""
    if group <= 1:
        return candles[:]
    out: list[list] = []
    full = len(candles) - (len(candles) % group)
    for i in range(0, full, group):
        chunk = candles[i : i + group]
        if len(chunk) < group:
            continue
        ts = chunk[-1][0] if chunk and chunk[-1] else ""
        open_p = _f(chunk[0], 1)
        high_p = max(_f(r, 2) for r in chunk)
        low_p = min(_f(r, 3) for r in chunk)
        close_p = _f(chunk[-1], 4)
        vol = sum(_f(r, 5) for r in chunk)
        out.append([ts, str(open_p), str(high_p), str(low_p), str(close_p), str(vol)])
    return out


def backtest_three_soldiers_signal(
    candles: list[list],
    idx: int,
    base_interval: str,
    leverage: int,
    instrument_type: InstrumentType | str,
) -> ThreeSoldiersSignal | None:
    window = candles[: idx + 1]
    signals: list[ThreeSoldiersSignal | None] = []
    if base_interval == "1H":
        signals.append(detect_three_white_soldiers(window, "1H", leverage, instrument_type))
        signals.append(detect_three_black_crows(window, "1H", leverage, instrument_type))
    else:
        signals.append(detect_three_white_soldiers(window, "5m", leverage, instrument_type))
        signals.append(detect_three_black_crows(window, "5m", leverage, instrument_type))
        if (idx + 1) % 2 == 0:
            candles_10m = resample_ohlcv(window, 2)
            signals.append(detect_three_white_soldiers(candles_10m, "10m", leverage, instrument_type))
            signals.append(detect_three_black_crows(candles_10m, "10m", leverage, instrument_type))
        if (idx + 1) % 12 == 0:
            candles_1h = resample_ohlcv(window, 12)
            signals.append(detect_three_white_soldiers(candles_1h, "1H", leverage, instrument_type))
            signals.append(detect_three_black_crows(candles_1h, "1H", leverage, instrument_type))
    return best_three_candle_pattern(signals)


def signal_to_plan(signal: ThreeSoldiersSignal):
    from app.market.dynamic_sl_tp import DynamicSlTpPlan

    return DynamicSlTpPlan(
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        sl_pct=signal.sl_pct,
        tp_pct=signal.tp_pct,
        method=signal.reason,
    )
