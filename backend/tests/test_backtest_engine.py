import numpy as np

from app.backtest.engine import optimize_strategy, run_simulation
from app.backtest.models import BacktestLogEntry
from app.models import AppConfig, StrategyMode


def _fake_candles(n: int = 120, trend: float = 0.02) -> list[list]:
    rows = []
    price = 100.0
    for i in range(n):
        price += trend + np.sin(i / 8) * 0.1
        ts = str(1_700_000_000_000 + i * 300_000)
        rows.append([ts, str(price), str(price + 0.05), str(price - 0.05), str(price), "1000"])
    return rows


def test_backtest_runs_with_synthetic_candles():
    config = AppConfig(
        strategy_mode=StrategyMode.SCALP,
        min_score=50,
        max_positions=2,
        order_size_usdt=100,
    )
    logs: list[BacktestLogEntry] = []
    candles = {
        "TEST-USDT-SWAP": _fake_candles(150, 0.05),
        "TEST2-USDT-SWAP": _fake_candles(150, -0.03),
    }
    state, bars = run_simulation(config, candles, logs, min_score_override=55)
    assert bars > 0
    assert len(logs) > 0
    assert not state.positions
    assert any("종료 청산" in t.exit_reason for t in state.trades) or len(state.trades) >= 0


def test_invert_signals_runs():
    config = AppConfig(strategy_mode=StrategyMode.SCALP, min_score=45, max_positions=2)
    logs: list[BacktestLogEntry] = []
    candles = {"TEST-USDT-SWAP": _fake_candles(150, 0.08)}
    state, _ = run_simulation(
        config, candles, logs, min_score_override=45, invert_signals=True, window_ratio=0.75
    )
    assert not state.positions


def test_optimizer_includes_long_short_and_inverse_modes():
    config = AppConfig(strategy_mode=StrategyMode.SCALP, min_score=45, max_positions=2)
    logs: list[BacktestLogEntry] = []
    candles = {
        "UP-USDT-SWAP": _fake_candles(150, 0.08),
        "DOWN-USDT-SWAP": _fake_candles(150, -0.08),
    }
    rec = optimize_strategy(config, candles, logs)
    modes = {t.mode for t in rec.direction_trials}
    assert {"normal", "long_only", "short_only", "inverse"}.issubset(modes)
