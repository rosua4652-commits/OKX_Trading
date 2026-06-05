"""SL/TP helpers using PnL ROI percent as the user-facing percent."""

from __future__ import annotations

from app.models import InstrumentType, PositionSide


def pnl_pct_to_price_pct(
    pnl_pct: float,
    leverage: int = 1,
    instrument_type: InstrumentType | str | None = None,
) -> float:
    """Convert user-facing PnL ROI% to raw price-move%."""
    if instrument_type in (InstrumentType.SPOT, "spot"):
        return pnl_pct
    return pnl_pct / max(1, leverage)


def price_pct_to_pnl_pct(
    price_pct: float,
    leverage: int = 1,
    instrument_type: InstrumentType | str | None = None,
) -> float:
    """Convert raw price-move% to user-facing PnL ROI%."""
    if instrument_type in (InstrumentType.SPOT, "spot"):
        return price_pct
    return price_pct * max(1, leverage)


def leverage_safe_sl_pct(
    sl_pct: float,
    leverage: int = 1,
    instrument_type: InstrumentType | str | None = None,
) -> float:
    """Cap SL ROI% so the price stop stays well inside liquidation danger."""
    if instrument_type in (InstrumentType.SPOT, "spot"):
        return sl_pct
    lev = max(1, leverage)
    max_price_move_pct = max(0.2, (100 / lev) * 0.65)
    return min(sl_pct, max_price_move_pct * lev)


def sl_tp_prices_from_pct(
    entry: float,
    side: PositionSide,
    sl_pct: float,
    tp_pct: float,
    leverage: int = 1,
    instrument_type: InstrumentType | str | None = None,
) -> tuple[float, float]:
    if entry <= 0:
        raise ValueError("진입가가 없습니다")
    sl_pct = leverage_safe_sl_pct(sl_pct, leverage, instrument_type)
    sl_r = pnl_pct_to_price_pct(sl_pct, leverage, instrument_type) / 100.0
    tp_r = pnl_pct_to_price_pct(tp_pct, leverage, instrument_type) / 100.0
    if side == PositionSide.LONG:
        return entry * (1 - sl_r), entry * (1 + tp_r)
    return entry * (1 + sl_r), entry * (1 - tp_r)


def validate_sl_tp(
    entry: float,
    side: PositionSide,
    sl_pct: float,
    tp_pct: float,
    leverage: int = 1,
    instrument_type: InstrumentType | str | None = None,
) -> str | None:
    if sl_pct < 0.05 or sl_pct > 80:
        return "손절 PnL%는 0.05~80 사이여야 합니다"
    if tp_pct < 0.05 or tp_pct > 200:
        return "익절 PnL%는 0.05~200 사이여야 합니다"
    safe_sl = leverage_safe_sl_pct(sl_pct, leverage, instrument_type)
    if safe_sl < sl_pct:
        return f"손절이 레버리지 {max(1, leverage)}x 기준 위험 구간에 가깝습니다. 최대 {safe_sl:.2f}%까지 가능합니다"
    try:
        sl, tp = sl_tp_prices_from_pct(
            entry,
            side,
            sl_pct,
            tp_pct,
            leverage,
            instrument_type,
        )
    except ValueError as e:
        return str(e)
    if side == PositionSide.LONG:
        if sl >= entry:
            return "롱 손절가는 진입가보다 낮아야 합니다"
        if tp <= entry:
            return "롱 익절가는 진입가보다 높아야 합니다"
    else:
        if sl <= entry:
            return "숏 손절가는 진입가보다 높아야 합니다"
        if tp >= entry:
            return "숏 익절가는 진입가보다 낮아야 합니다"
    return None
