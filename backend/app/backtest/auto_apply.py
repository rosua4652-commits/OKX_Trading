"""Apply backtest recommendations to live AppConfig."""

from __future__ import annotations

from app.backtest.models import BacktestResult
from app.models import AppConfig


def build_config_from_backtest(current: AppConfig, result: BacktestResult) -> AppConfig | None:
    if result.status != "done" or not result.recommendation:
        return None

    rec = result.recommendation
    apply_score = current.backtest_auto_settings
    apply_sl_tp = current.backtest_auto_sl_tp
    if not apply_score and not apply_sl_tp:
        return None

    cfg = current.model_copy(deep=True)
    changed = False

    if apply_score:
        cfg.min_score = float(rec.min_score)
        changed = True

    if apply_sl_tp and rec.stop_loss_pct > 0 and rec.take_profit_pct > 0:
        cfg.stop_loss_pct = round(float(rec.stop_loss_pct), 2)
        cfg.take_profit_pct = round(float(rec.take_profit_pct), 2)
        changed = True

    return cfg if changed else None


def config_changed(before: AppConfig, after: AppConfig) -> bool:
    return (
        before.min_score != after.min_score
        or before.position_size_mode != after.position_size_mode
        or before.order_size_pct != after.order_size_pct
        or before.stop_loss_pct != after.stop_loss_pct
        or before.take_profit_pct != after.take_profit_pct
    )
