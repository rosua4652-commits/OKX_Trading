from app.backtest.auto_apply import build_config_from_backtest, config_changed
from app.backtest.models import BacktestMetrics, BacktestRecommendation, BacktestResult
from app.models import AppConfig


def test_build_config_auto_applies_fluid_settings():
    cfg = AppConfig(min_score=55, position_size_mode="fixed", backtest_auto_settings=True)
    result = BacktestResult(
        id="t1",
        status="done",
        started_at="",
        strategy_mode="scalp",
        recommendation=BacktestRecommendation(min_score=62, reason="test"),
        metrics=BacktestMetrics(),
    )
    out = build_config_from_backtest(cfg, result)
    assert out is not None
    assert out.min_score == 62
    assert out.position_size_mode == "pct_available"
    assert config_changed(cfg, out)


def test_manual_mode_skips_auto_apply():
    cfg = AppConfig(backtest_auto_settings=False)
    result = BacktestResult(
        id="t1",
        status="done",
        started_at="",
        strategy_mode="scalp",
        recommendation=BacktestRecommendation(min_score=62, reason="test"),
    )
    assert build_config_from_backtest(cfg, result) is None
