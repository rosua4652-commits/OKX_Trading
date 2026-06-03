"""Strategy mode helpers — scalp + swing simultaneous support."""

from __future__ import annotations

from app.config import settings
from app.models import AppConfig, StrategyMode


def active_strategies(config: AppConfig) -> list[StrategyMode]:
    if config.strategy_mode == StrategyMode.BOTH:
        return [StrategyMode.SCALP, StrategyMode.SWING]
    return [config.strategy_mode]


def sl_tp_pcts(config: AppConfig, strategy: StrategyMode) -> tuple[float, float]:
    if strategy == StrategyMode.SWING:
        return settings.swing_stop_loss_pct, settings.swing_take_profit_pct
    return settings.default_stop_loss_pct, settings.default_take_profit_pct
