"""SL/TP price helpers — manual per-position overrides."""

from __future__ import annotations

from app.models import PositionSide


def sl_tp_prices_from_pct(
    entry: float,
    side: PositionSide,
    sl_pct: float,
    tp_pct: float,
) -> tuple[float, float]:
    if entry <= 0:
        raise ValueError("진입가가 없습니다")
    sl_r = sl_pct / 100.0
    tp_r = tp_pct / 100.0
    if side == PositionSide.LONG:
        return entry * (1 - sl_r), entry * (1 + tp_r)
    return entry * (1 + sl_r), entry * (1 - tp_r)


def validate_sl_tp(
    entry: float,
    side: PositionSide,
    sl_pct: float,
    tp_pct: float,
) -> str | None:
    if sl_pct < 0.05 or sl_pct > 80:
        return "손절 %는 0.05~80 사이여야 합니다"
    if tp_pct < 0.05 or tp_pct > 200:
        return "익절 %는 0.05~200 사이여야 합니다"
    try:
        sl, tp = sl_tp_prices_from_pct(entry, side, sl_pct, tp_pct)
    except ValueError as e:
        return str(e)
    if side == PositionSide.LONG:
        if sl >= entry:
            return "롱: 손절가는 진입가보다 낮아야 합니다"
        if tp <= entry:
            return "롱: 익절가는 진입가보다 높아야 합니다"
    else:
        if sl <= entry:
            return "숏: 손절가는 진입가보다 높아야 합니다"
        if tp >= entry:
            return "숏: 익절가는 진입가보다 낮아야 합니다"
    return None
