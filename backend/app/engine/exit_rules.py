"""Exit rules: stop loss, take profit, and delayed profit protection."""

from __future__ import annotations

import time

from app.config import settings
from app.models import AppConfig, Position, StrategyMode
from app.strategy_utils import sl_tp_pcts


def _fee_buffer_roi(pos: Position, config: AppConfig) -> float:
    """Minimum ROI% where profit remains after round-trip fees and leverage."""
    lev = max(1, pos.leverage or config.leverage or 1)
    round_trip_fee_roi = settings.trading_fee_pct * lev * 2
    return max(0.8, round_trip_fee_roi * 1.5 + 0.4)


def _profit_protect_floor_pct(pos: Position, config: AppConfig, tp_pct: float) -> float:
    trigger_ratio = max(0.0, float(config.profit_protect_trigger_pct or 0.0)) / 100.0
    tp_based_trigger = max(0.0, tp_pct * trigger_ratio)
    fee_floor = _fee_buffer_roi(pos, config)
    if tp_pct > 0:
        return max(fee_floor, min(tp_based_trigger, tp_pct))
    return fee_floor


def _profit_protect_exit(pos: Position, config: AppConfig, tp_pct: float) -> tuple[bool, str]:
    if pos.strategy_mode != StrategyMode.SCALP or not config.trailing_stop:
        return False, ""
    if pos.auto_profit_protect_disabled or pos.entry_price <= 0:
        return False, ""
    if pos.unrealized_pnl <= 0:
        pos.profit_protect_armed_at = 0.0
        pos.profit_protect_floor_pct = 0.0
        return False, ""

    floor_pct = _profit_protect_floor_pct(pos, config, tp_pct)
    current_roi = pos.unrealized_pnl_pct
    is_bt = str(pos.id).startswith("bt:")
    if is_bt:
        try:
            now = float(str(pos.id).split(":", 1)[1])
        except (IndexError, ValueError):
            now = 0.0
    else:
        now = time.time()

    if current_roi >= floor_pct:
        if pos.profit_protect_armed_at <= 0:
            pos.profit_protect_armed_at = now
            pos.profit_protect_floor_pct = floor_pct
            return False, ""
        hold_req = (
            (1 if int(config.profit_protect_confirm_sec or 0) > 0 else 0)
            if is_bt
            else max(0, int(config.profit_protect_confirm_sec or 0))
        )
        if now - pos.profit_protect_armed_at < hold_req:
            return False, ""
        pos.profit_protect_floor_pct = floor_pct
        return False, ""

    armed = pos.profit_protect_armed_at > 0
    hold_req = (
        (1 if int(config.profit_protect_confirm_sec or 0) > 0 else 0)
        if is_bt
        else max(0, int(config.profit_protect_confirm_sec or 0))
    )
    confirmed = armed and (now - pos.profit_protect_armed_at >= hold_req)
    if confirmed and current_roi < max(floor_pct, pos.profit_protect_floor_pct):
        return True, f"수익 보호 익절 (보호선 {floor_pct:.1f}% 이탈, 현재 {current_roi:.1f}%)"

    if not armed:
        pos.profit_protect_floor_pct = 0.0
    return False, ""


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

    if not tp_disabled:
        protect_exit, protect_reason = _profit_protect_exit(pos, config, tp_pct)
        if protect_exit:
            return True, protect_reason

    if not sl_disabled and pos.side.value == "long" and price <= pos.stop_loss:
        return True, f"손절 PnL({sl_pct}%)"
    if not tp_disabled and pos.side.value == "long" and price >= pos.take_profit:
        return True, f"익절 PnL({tp_pct}%)"
    if not sl_disabled and pos.side.value == "short" and price >= pos.stop_loss:
        return True, f"손절 PnL({sl_pct}%)"
    if not tp_disabled and pos.side.value == "short" and price <= pos.take_profit:
        return True, f"익절 PnL({tp_pct}%)"

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
