"""Exit rules: stop loss, take profit, trailing stop."""

from __future__ import annotations

from app.config import settings
from app.models import AppConfig, Position, PositionSide, StrategyMode
from app.strategy_utils import sl_tp_pcts


def should_exit(
    pos: Position,
    config: AppConfig,
) -> tuple[bool, str]:
    if pos.auto_sl_tp_disabled:
        return False, ""

    price = pos.current_price
    if price <= 0:
        return False, ""

    sl_disabled = bool(pos.auto_sl_disabled)
    tp_disabled = bool(pos.auto_tp_disabled)
    sl_pct = pos.sl_pct if pos.sl_pct > 0 else sl_tp_pcts(config, pos.strategy_mode)[0]
    tp_pct = pos.tp_pct if pos.tp_pct > 0 else sl_tp_pcts(config, pos.strategy_mode)[1]

    if not sl_disabled and pos.sl_usdt > 0 and pos.unrealized_pnl <= -abs(pos.sl_usdt):
        return True, f"손절 PnL(USDT {pos.sl_usdt:g})"
    if not tp_disabled and pos.tp_usdt > 0 and pos.unrealized_pnl >= abs(pos.tp_usdt):
        return True, f"익절 PnL(USDT {pos.tp_usdt:g})"

    if pos.side == PositionSide.LONG:
        if not sl_disabled and price <= pos.stop_loss:
            return True, f"손절 PnL({sl_pct}%)"
        if not tp_disabled and price >= pos.take_profit:
            return True, f"익절 PnL({tp_pct}%)"
        if not sl_disabled and config.trailing_stop and pos.trailing_high > pos.entry_price:
            activate = pos.entry_price * (1 + settings.trailing_activate_pct / 100)
            if pos.trailing_high >= activate:
                trail_stop = pos.trailing_high * (1 - settings.trailing_distance_pct / 100)
                if price <= trail_stop:
                    return True, "트레일링 스탑"
    else:
        if not sl_disabled and price >= pos.stop_loss:
            return True, f"손절 PnL({sl_pct}%)"
        if not tp_disabled and price <= pos.take_profit:
            return True, f"익절 PnL({tp_pct}%)"
        if not sl_disabled and config.trailing_stop and pos.trailing_high < pos.entry_price:
            activate = pos.entry_price * (1 - settings.trailing_activate_pct / 100)
            if pos.trailing_high <= activate:
                trail_stop = pos.trailing_high * (1 + settings.trailing_distance_pct / 100)
                if price >= trail_stop:
                    return True, "트레일링 스탑"

    pnl_pct = pos.unrealized_pnl_pct
    if (
        not sl_disabled
        and pos.strategy_mode == StrategyMode.SCALP
        and pnl_pct <= -sl_pct * 1.5
    ):
        return True, "긴급 손절 PnL(단타)"

    return False, ""


def apply_strategy_defaults(config: AppConfig) -> AppConfig:
    if config.stop_loss_pct <= 0:
        config.stop_loss_pct = settings.default_stop_loss_pct
    if config.take_profit_pct <= 0:
        config.take_profit_pct = settings.default_take_profit_pct
    return config
