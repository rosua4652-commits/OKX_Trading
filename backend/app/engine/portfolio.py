"""Portfolio and position management."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.config import settings
from app.contract_sizing import classify_close_type, swap_margin_usdt
from app.sl_tp_utils import (
    pnl_pct_to_price_pct,
    price_pct_to_pnl_pct,
    sl_tp_prices_from_pct,
    validate_sl_tp,
)
from app.strategy_utils import sl_tp_pcts
from app.models import (
    AppConfig,
    InstrumentType,
    PortfolioSnapshot,
    Position,
    PositionSide,
    StrategyMode,
    TradeMode,
    TradeRecord,
    utc_now_iso,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _position_notional(pos: Position) -> float:
    if pos.notional_usdt > 0:
        return pos.notional_usdt
    return pos.entry_price * pos.quantity


def _pnl_from_prices(
    side: PositionSide,
    entry: float,
    exit_price: float,
    notional: float,
) -> float:
    if entry <= 0 or notional <= 0:
        return 0.0
    if side == PositionSide.LONG:
        return notional * (exit_price - entry) / entry
    return notional * (entry - exit_price) / entry


class PortfolioManager:
    def __init__(self, mode: TradeMode, initial_balance: float | None = None) -> None:
        self.mode = mode
        self.balance = initial_balance or settings.initial_balance
        self.available = self.balance
        self.realized_pnl = 0.0
        self.positions: dict[str, Position] = {}
        self.trades: list[TradeRecord] = []
        self.stats_reset_at = ""
        self._file = DATA_DIR / f"portfolio_{mode.value}.json"

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "balance": self.balance,
            "initial_balance": self.balance,
            "available": self.available,
            "realized_pnl": self.realized_pnl,
            "positions": {k: v.model_dump() for k, v in self.positions.items()},
            "trades": [t.model_dump() for t in self.trades[-500:]],
            "stats_reset_at": self.stats_reset_at,
        }
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def reset(self, initial_balance: float | None = None) -> None:
        bal = initial_balance if initial_balance is not None else settings.initial_balance
        if bal <= 0:
            bal = settings.initial_balance if settings.initial_balance > 0 else 10_000.0
        self.balance = bal
        self.available = bal
        self.realized_pnl = 0.0
        self.positions = {}
        self.trades = []
        self.stats_reset_at = ""
        self.save()

    def reset_stats(self) -> None:
        self.realized_pnl = 0.0
        self.trades = []
        self.stats_reset_at = utc_now_iso()
        self.save()

    def load(self) -> None:
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text())
            self.balance = float(data.get("balance", self.balance))
            self.available = float(data.get("available", self.available))
            self.realized_pnl = float(data.get("realized_pnl", 0))
            self.stats_reset_at = str(data.get("stats_reset_at") or "")
            self.positions = {
                k: Position(**v) for k, v in data.get("positions", {}).items()
            }
            self.trades = [TradeRecord(**t) for t in data.get("trades", [])]
        except Exception:
            pass

    def open_position(
        self,
        inst_id: str,
        side: PositionSide,
        quantity: float,
        entry_price: float,
        config: AppConfig,
        reason: str = "",
        score: float = 0.0,
        strategy_mode: StrategyMode | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        sl_pct: float = 0.0,
        tp_pct: float = 0.0,
        sl_tp_note: str = "",
        notional_usdt: float | None = None,
    ) -> Position | None:
        strat = strategy_mode or config.strategy_mode
        if strat == StrategyMode.BOTH:
            strat = StrategyMode.SCALP

        lev = max(1, config.leverage) if config.instrument_type != InstrumentType.SPOT else 1
        if notional_usdt is not None and notional_usdt > 0:
            notional = notional_usdt
        else:
            notional = quantity * entry_price

        if config.instrument_type != InstrumentType.SPOT:
            margin = swap_margin_usdt(notional, lev)
        else:
            margin = notional

        fee = notional * settings.trading_fee_pct / 100
        if self.available < margin + fee:
            return None

        if stop_loss is not None and take_profit is not None:
            sl, tp = stop_loss, take_profit
            if entry_price > 0:
                if side == PositionSide.SHORT:
                    sl_price_pct = max(0.0, (sl - entry_price) / entry_price * 100)
                    tp_price_pct = max(0.0, (entry_price - tp) / entry_price * 100)
                else:
                    sl_price_pct = max(0.0, (entry_price - sl) / entry_price * 100)
                    tp_price_pct = max(0.0, (tp - entry_price) / entry_price * 100)
                sl_pct = round(price_pct_to_pnl_pct(sl_price_pct, lev, config.instrument_type), 2)
                tp_pct = round(price_pct_to_pnl_pct(tp_price_pct, lev, config.instrument_type), 2)
        else:
            sl_pct_val, tp_pct_val = sl_tp_pcts(config, strat)
            sl_r = pnl_pct_to_price_pct(
                sl_pct_val,
                lev,
                config.instrument_type,
            ) / 100
            tp_r = pnl_pct_to_price_pct(
                tp_pct_val,
                lev,
                config.instrument_type,
            ) / 100
            if side == PositionSide.LONG:
                sl = entry_price * (1 - sl_r)
                tp = entry_price * (1 + tp_r)
            else:
                sl = entry_price * (1 + sl_r)
                tp = entry_price * (1 - tp_r)
            sl_pct = sl_pct or sl_pct_val
            tp_pct = tp_pct or tp_pct_val

        pos = Position(
            id=str(uuid.uuid4())[:8],
            inst_id=inst_id,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            sl_tp_note=sl_tp_note,
            trailing_high=entry_price,
            strategy_mode=strat,
            instrument_type=config.instrument_type,
            entry_reason=reason,
            entry_score=score,
            opened_at=utc_now_iso(),
            leverage=lev if config.instrument_type != InstrumentType.SPOT else 1,
            notional_usdt=round(notional, 2),
            last_scale_price=entry_price,
        )
        self.positions[inst_id] = pos
        self.available -= margin + fee
        self.save()
        return pos

    def add_to_position(
        self,
        inst_id: str,
        quantity: float,
        price: float,
        config: AppConfig,
        reason: str = "",
        notional_usdt: float | None = None,
    ) -> Position | None:
        pos = self.positions.get(inst_id)
        if not pos or quantity <= 0 or price <= 0:
            return None

        old_notional = _position_notional(pos)
        add_notional = notional_usdt if notional_usdt and notional_usdt > 0 else quantity * price
        lev = max(1, pos.leverage or config.leverage or 1)
        margin = swap_margin_usdt(add_notional, lev) if pos.instrument_type != InstrumentType.SPOT else add_notional
        fee = add_notional * settings.trading_fee_pct / 100
        if self.available < margin + fee:
            return None

        new_qty = pos.quantity + quantity
        new_notional = old_notional + add_notional
        if new_qty <= 0 or new_notional <= 0:
            return None

        pos.entry_price = ((pos.entry_price * pos.quantity) + (price * quantity)) / new_qty
        pos.quantity = new_qty
        pos.current_price = price
        pos.notional_usdt = round(new_notional, 2)
        pos.scale_in_count += 1
        pos.last_scale_price = price
        if reason:
            pos.entry_reason = f"{pos.entry_reason} | {reason}" if pos.entry_reason else reason

        sl, tp = sl_tp_prices_from_pct(
            pos.entry_price,
            pos.side,
            pos.sl_pct,
            pos.tp_pct,
            pos.leverage or 1,
            pos.instrument_type,
        )
        pos.stop_loss = round(sl, 12)
        pos.take_profit = round(tp, 12)
        if pos.sl_usdt > 0 or pos.tp_usdt > 0:
            margin_total = swap_margin_usdt(new_notional, lev) if pos.instrument_type != InstrumentType.SPOT else new_notional
            if pos.sl_pct > 0:
                pos.sl_usdt = round(abs(margin_total * pos.sl_pct / 100), 6)
            if pos.tp_pct > 0:
                pos.tp_usdt = round(abs(margin_total * pos.tp_pct / 100), 6)

        self.available -= margin + fee
        self.update_prices({inst_id: price})
        self.save()
        return pos

    def close_position(
        self,
        inst_id: str,
        exit_price: float,
        reason: str = "",
    ) -> TradeRecord | None:
        pos = self.positions.pop(inst_id, None)
        if not pos:
            return None

        notional = _position_notional(pos)
        pnl = _pnl_from_prices(pos.side, pos.entry_price, exit_price, notional)
        fee = notional * settings.trading_fee_pct / 100
        pnl -= fee
        lev = max(1, pos.leverage or 1)
        if pos.instrument_type != InstrumentType.SPOT:
            margin = swap_margin_usdt(notional, lev)
        else:
            margin = notional
        pnl_pct = pnl / margin * 100 if margin > 0 else 0.0

        self.available += margin + pnl
        self.realized_pnl += pnl

        trade = TradeRecord(
            id=str(uuid.uuid4())[:8],
            inst_id=inst_id,
            side="sell" if pos.side == PositionSide.LONG else "buy",
            quantity=pos.quantity,
            price=exit_price,
            pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            reason=reason,
            close_type=classify_close_type(reason),
            position_side=pos.side.value,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            notional_usdt=round(notional, 2),
            strategy_mode=pos.strategy_mode.value if hasattr(pos.strategy_mode, "value") else str(pos.strategy_mode),
            mode=self.mode,
            ts=utc_now_iso(),
        )
        self.trades.append(trade)
        self.save()
        return trade

    def apply_sl_tp_plan(self, inst_id: str, plan) -> None:
        pos = self.positions.get(inst_id)
        if not pos:
            return
        if pos.sl_tp_manual:
            return
        pos.stop_loss = plan.stop_loss
        pos.take_profit = plan.take_profit
        if pos.entry_price > 0:
            if pos.side == PositionSide.SHORT:
                sl_price_pct = max(0.0, (plan.stop_loss - pos.entry_price) / pos.entry_price * 100)
                tp_price_pct = max(0.0, (pos.entry_price - plan.take_profit) / pos.entry_price * 100)
            else:
                sl_price_pct = max(0.0, (pos.entry_price - plan.stop_loss) / pos.entry_price * 100)
                tp_price_pct = max(0.0, (plan.take_profit - pos.entry_price) / pos.entry_price * 100)
            pos.sl_pct = round(price_pct_to_pnl_pct(sl_price_pct, pos.leverage or 1, pos.instrument_type), 2)
            pos.tp_pct = round(price_pct_to_pnl_pct(tp_price_pct, pos.leverage or 1, pos.instrument_type), 2)
        else:
            pos.sl_pct = plan.sl_pct
            pos.tp_pct = plan.tp_pct
        pos.sl_tp_note = "수동 PnL 기준"
        self.save()

    def set_sl_tp_manual(
        self,
        inst_id: str,
        sl_pct: float,
        tp_pct: float,
    ) -> tuple[bool, str]:
        pos = self.positions.get(inst_id)
        if not pos:
            return False, "포지션 없음"
        err = validate_sl_tp(
            pos.entry_price,
            pos.side,
            sl_pct,
            tp_pct,
            pos.leverage or 1,
            pos.instrument_type,
        )
        if err:
            return False, err
        sl, tp = sl_tp_prices_from_pct(
            pos.entry_price,
            pos.side,
            sl_pct,
            tp_pct,
            pos.leverage or 1,
            pos.instrument_type,
        )
        pos.stop_loss = round(sl, 12)
        pos.take_profit = round(tp, 12)
        pos.sl_pct = round(sl_pct, 2)
        pos.tp_pct = round(tp_pct, 2)
        notional = _position_notional(pos)
        lev = max(1, pos.leverage or 1)
        margin = swap_margin_usdt(notional, lev) if pos.instrument_type != InstrumentType.SPOT else notional
        pos.sl_usdt = round(abs(margin * sl_pct / 100), 6)
        pos.tp_usdt = round(abs(margin * tp_pct / 100), 6)
        pos.sl_tp_note = "수동 PnL 기준"
        pos.sl_tp_manual = True
        self.save()
        return True, "OK"

    def clear_sl_tp_manual(self, inst_id: str) -> bool:
        pos = self.positions.get(inst_id)
        if not pos:
            return False
        pos.sl_tp_manual = False
        self.save()
        return True

    def update_prices(self, prices: dict[str, float]) -> None:
        for inst_id, pos in self.positions.items():
            price = prices.get(inst_id, pos.current_price)
            pos.current_price = price
            notional = _position_notional(pos)
            pos.unrealized_pnl = _pnl_from_prices(pos.side, pos.entry_price, price, notional)
            lev = max(1, pos.leverage or 1)
            margin = swap_margin_usdt(notional, lev) if pos.instrument_type != InstrumentType.SPOT else notional
            pos.unrealized_pnl_pct = pos.unrealized_pnl / margin * 100 if margin > 0 else 0
            if pos.side == PositionSide.LONG:
                pos.trailing_high = max(pos.trailing_high, price)
            else:
                pos.trailing_high = min(pos.trailing_high, price) if pos.trailing_high > 0 else price

    def snapshot(self) -> PortfolioSnapshot:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        if self.mode == TradeMode.LIVE and self.balance > 0:
            equity = round(self.balance, 2)
        else:
            margin_locked = 0.0
            for p in self.positions.values():
                n = _position_notional(p)
                lev = max(1, p.leverage or 1)
                if p.instrument_type != InstrumentType.SPOT:
                    margin_locked += swap_margin_usdt(n, lev)
                else:
                    margin_locked += n
            equity = round(self.available + margin_locked + unrealized, 2)
        wins = sum(1 for t in self.trades if t.pnl > 0)
        total = len(self.trades)
        return PortfolioSnapshot(
            balance=self.balance,
            equity=round(equity, 2),
            available=round(self.available, 2),
            unrealized_pnl=round(unrealized, 2),
            realized_pnl=round(self.realized_pnl, 2),
            positions=list(self.positions.values()),
            trade_count=total,
            win_rate=round(wins / total * 100, 1) if total > 0 else 0.0,
        )
