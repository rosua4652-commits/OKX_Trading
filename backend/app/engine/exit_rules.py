"""Exit rules — stop loss, take profit, trailing stop."""

from __future__ import annotations

from app.config import settings
from app.models import AppConfig, Position, PositionSide, StrategyMode


def should_exit(
    pos: Position,
    config: AppConfig,
) -> tuple[bool, str]:
    price = pos.current_price
    if price <= 0:
        return False, ""

    if pos.side == PositionSide.LONG:
        if price <= pos.stop_loss:
            return True, f"손절 ({config.stop_loss_pct}%)"
        if price >= pos.take_profit:
            return True, f"익절 ({config.take_profit_pct}%)"
        if config.trailing_stop and pos.trailing_high > pos.entry_price:
            activate = pos.entry_price * (1 + settings.trailing_activate_pct / 100)
            if pos.trailing_high >= activate:
                trail_stop = pos.trailing_high * (1 - settings.trailing_distance_pct / 100)
                if price <= trail_stop:
                    return True, "트레일링 스탑"
    else:
        if price >= pos.stop_loss:
            return True, f"손절 ({config.stop_loss_pct}%)"
        if price <= pos.take_profit:
            return True, f"익절 ({config.take_profit_pct}%)"
        if config.trailing_stop and pos.trailing_high < pos.entry_price:
            activate = pos.entry_price * (1 - settings.trailing_activate_pct / 100)
            if pos.trailing_high <= activate:
                trail_stop = pos.trailing_high * (1 + settings.trailing_distance_pct / 100)
                if price >= trail_stop:
                    return True, "트레일링 스탑"

    pnl_pct = pos.unrealized_pnl_pct
    if pos.strategy_mode == StrategyMode.SCALP and pnl_pct <= -config.stop_loss_pct * 1.5:
        return True, "긴급 손절 (단타)"

    return False, ""


def apply_strategy_defaults(config: AppConfig) -> AppConfig:
    if config.strategy_mode == StrategyMode.SWING:
        config.stop_loss_pct = settings.swing_stop_loss_pct
        config.take_profit_pct = settings.swing_take_profit_pct
    else:
        config.stop_loss_pct = settings.default_stop_loss_pct
        config.take_profit_pct = settings.default_take_profit_pct
    return config
