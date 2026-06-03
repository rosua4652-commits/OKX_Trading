from app.backtest.auto_apply import build_config_from_backtest, config_changed
from app.backtest.history_sl_tp import exit_stats_from_trades, merge_sl_tp_with_history
from app.backtest.models import BacktestMetrics, BacktestRecommendation, BacktestResult
from app.models import AppConfig


def test_build_config_auto_applies_fluid_settings():
    cfg = AppConfig(min_score=55, position_size_mode="fixed", backtest_auto_settings=True)
    result = BacktestResult(
        id="t1",
        status="done",
        started_at="",
        strategy_mode="scalp",
        recommendation=BacktestRecommendation(
            min_score=62,
            reason="test",
            stop_loss_pct=2.0,
            take_profit_pct=3.5,
        ),
        metrics=BacktestMetrics(),
    )
    out = build_config_from_backtest(cfg, result)
    assert out is not None
    assert out.min_score == 62
    assert out.position_size_mode == "fixed"
    assert config_changed(cfg, out)


def test_build_config_auto_applies_sl_tp_only():
    cfg = AppConfig(
        stop_loss_pct=2.0,
        take_profit_pct=3.0,
        backtest_auto_sl_tp=True,
    )
    result = BacktestResult(
        id="t2",
        status="done",
        started_at="",
        strategy_mode="scalp",
        recommendation=BacktestRecommendation(
            min_score=60,
            reason="test",
            stop_loss_pct=1.5,
            take_profit_pct=2.5,
        ),
    )
    out = build_config_from_backtest(cfg, result)
    assert out is not None
    assert out.min_score == 55.0
    assert out.stop_loss_pct == 1.5
    assert out.take_profit_pct == 2.5
    assert config_changed(cfg, out)


def test_manual_mode_skips_auto_apply():
    cfg = AppConfig(backtest_auto_settings=False, backtest_auto_sl_tp=False)
    result = BacktestResult(
        id="t1",
        status="done",
        started_at="",
        strategy_mode="scalp",
        recommendation=BacktestRecommendation(min_score=62, reason="test"),
    )
    assert build_config_from_backtest(cfg, result) is None


def test_exit_stats_from_trades():
    trades = [
        {"exit_reason": "손절 (2%)"},
        {"exit_reason": "익절 (3%)"},
        {"exit_reason": "백테스트 종료 청산"},
    ]
    stats = exit_stats_from_trades(trades)
    assert stats["sl"] == 1
    assert stats["tp"] == 1
    assert stats["end_close"] == 1


def test_merge_sl_tp_with_history():
    history = [
        {
            "status": "done",
            "metrics": {"win_rate": 80, "trade_count": 10},
            "recommendation": {"stop_loss_pct": 2.0, "take_profit_pct": 2.0},
            "exit_stats": {"end_close": 1},
        },
        {
            "status": "done",
            "metrics": {"win_rate": 70, "trade_count": 8},
            "recommendation": {"stop_loss_pct": 1.5, "take_profit_pct": 2.5},
            "exit_stats": {"end_close": 0},
        },
    ]
    sl, tp, note = merge_sl_tp_with_history(2.5, 4.0, history, use_history=True)
    assert 0.5 <= sl <= 8.0
    assert 0.8 <= tp <= 15.0
    assert "SL" in note
