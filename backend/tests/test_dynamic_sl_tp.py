"""Dynamic SL/TP from synthetic candles."""

from app.market.dynamic_sl_tp import plan_from_candles
from app.models import AppConfig, PositionSide, StrategyMode


def _fake_candles(base: float = 100.0, n: int = 60) -> list[list[str]]:
    rows = []
    for i in range(n):
        o = base + i * 0.1
        h = o + 0.5
        l = o - 0.3
        c = o + 0.2
        rows.append([str(i * 300_000), str(o), str(h), str(l), str(c), "1000"])
    return rows


def test_swing_wider_than_scalp():
    candles = _fake_candles()
    entry = 105.0
    cfg = AppConfig()
    scalp = plan_from_candles(candles, entry, PositionSide.LONG, StrategyMode.SCALP, cfg)
    swing = plan_from_candles(candles, entry, PositionSide.LONG, StrategyMode.SWING, cfg)
    assert swing.sl_pct >= scalp.sl_pct * 0.8
    assert swing.tp_pct >= scalp.tp_pct * 0.8


def test_long_sl_below_entry():
    candles = _fake_candles(base=0.000003)
    entry = 0.0000032
    plan = plan_from_candles(candles, entry, PositionSide.LONG, StrategyMode.SCALP, AppConfig())
    assert plan.stop_loss < entry
    assert plan.take_profit > entry
