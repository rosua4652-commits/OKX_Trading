from app.backtest.candles_util import build_symbol_charts
from app.backtest.models import BacktestTrade


def _candles(n: int, start: float = 100.0) -> list:
    rows = []
    p = start
    for i in range(n):
        p += 0.1
        rows.append(["0", str(p), str(p + 0.2), str(p - 0.1), str(p + 0.05), "1"])
    return rows


def test_build_symbol_charts_with_markers():
    trades = [
        BacktestTrade(
            inst_id="BTC-USDT-SWAP",
            side="long",
            strategy="scalp",
            entry_bar=80,
            exit_bar=90,
            entry_price=100,
            exit_price=101,
            score=60,
            sl_pct=2,
            tp_pct=3,
            pnl_usdt=1,
            pnl_pct=1,
            exit_reason="익절",
        ),
    ]
    charts = build_symbol_charts({"BTC-USDT-SWAP": _candles(100)}, trades, display_bars=30)
    assert "BTC-USDT-SWAP" in charts
    ch = charts["BTC-USDT-SWAP"]
    assert len(ch.bars) == 30
    assert ch.total_bars == 100
    assert ch.trade_markers[0]["entry"] == 80 - 70
