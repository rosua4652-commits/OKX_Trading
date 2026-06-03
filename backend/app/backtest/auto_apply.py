"""Apply backtest recommendations to live AppConfig."""

from __future__ import annotations

from app.backtest.models import BacktestResult
from app.models import AppConfig


def build_config_from_backtest(current: AppConfig, result: BacktestResult) -> AppConfig | None:
    if not current.backtest_auto_settings:
        return None
    if not result.recommendation or result.status != "done":
        return None

    rec = result.recommendation
    cfg = current.model_copy(deep=True)
    cfg.min_score = float(rec.min_score)
    cfg.position_size_mode = "pct_available"
    if cfg.order_size_pct < 0.5:
        cfg.order_size_pct = 2.0
    return cfg


def config_changed(before: AppConfig, after: AppConfig) -> bool:
    return (
        before.min_score != after.min_score
        or before.position_size_mode != after.position_size_mode
        or before.order_size_pct != after.order_size_pct
    )
