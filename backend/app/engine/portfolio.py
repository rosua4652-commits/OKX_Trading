"""Portfolio and position management."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.config import settings
from app.models import (
    AppConfig,
    PortfolioSnapshot,
    Position,
    PositionSide,
    StrategyMode,
    TradeMode,
    TradeRecord,
    utc_now_iso,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class PortfolioManager:
    def __init__(self, mode: TradeMode, initial_balance: float | None = None) -> None:
        self.mode = mode
        self.balance = initial_balance or settings.initial_balance
        self.available = self.balance
        self.realized_pnl = 0.0
        self.positions: dict[str, Position] = {}
        self.trades: list[TradeRecord] = []
        self._file = DATA_DIR / f"portfolio_{mode.value}.json"

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "balance": self.balance,
            "available": self.available,
            "realized_pnl": self.realized_pnl,
            "positions": {k: v.model_dump() for k, v in self.positions.items()},
            "trades": [t.model_dump() for t in self.trades[-500:]],
        }
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def load(self) -> None:
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text())
            self.balance = float(data.get("balance", self.balance))
            self.available = float(data.get("available", self.available))
            self.realized_pnl = float(data.get("realized_pnl", 0))
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
    ) -> Position | None:
        cost = quantity * entry_price
        fee = cost * settings.trading_fee_pct / 100
        if self.available < cost + fee:
            return None

        sl_pct = config.stop_loss_pct / 100
        tp_pct = config.take_profit_pct / 100

        if side == PositionSide.LONG:
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)
        else:
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - tp_pct)

        pos = Position(
            id=str(uuid.uuid4())[:8],
            inst_id=inst_id,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            trailing_high=entry_price,
            strategy_mode=config.strategy_mode,
            instrument_type=config.instrument_type,
            entry_reason=reason,
            entry_score=score,
            opened_at=utc_now_iso(),
        )
        self.positions[inst_id] = pos
        self.available -= cost + fee
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

        if pos.side == PositionSide.LONG:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        fee = exit_price * pos.quantity * settings.trading_fee_pct / 100
        pnl -= fee
        pnl_pct = pnl / (pos.entry_price * pos.quantity) * 100 if pos.entry_price > 0 else 0

        self.available += pos.entry_price * pos.quantity + pnl
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
            mode=self.mode,
            ts=utc_now_iso(),
        )
        self.trades.append(trade)
        self.save()
        return trade

    def update_prices(self, prices: dict[str, float]) -> None:
        for inst_id, pos in self.positions.items():
            price = prices.get(inst_id, pos.current_price)
            pos.current_price = price
            if pos.side == PositionSide.LONG:
                pos.unrealized_pnl = (price - pos.entry_price) * pos.quantity
            else:
                pos.unrealized_pnl = (pos.entry_price - price) * pos.quantity
            cost = pos.entry_price * pos.quantity
            pos.unrealized_pnl_pct = pos.unrealized_pnl / cost * 100 if cost > 0 else 0
            if pos.side == PositionSide.LONG:
                pos.trailing_high = max(pos.trailing_high, price)
            else:
                pos.trailing_high = min(pos.trailing_high, price) if pos.trailing_high > 0 else price

    def snapshot(self) -> PortfolioSnapshot:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        equity = self.available + sum(
            p.entry_price * p.quantity + p.unrealized_pnl for p in self.positions.values()
        )
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
