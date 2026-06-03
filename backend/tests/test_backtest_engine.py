import numpy as np

from app.backtest.engine import run_simulation
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
