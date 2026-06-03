from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


OAT_BUILD = "2026-06-03-okx-v1"


class TradeMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class InstrumentType(str, Enum):
    SPOT = "spot"
    SWAP = "swap"
    FUTURES = "futures"


class StrategyMode(str, Enum):
    SCALP = "scalp"
    SWING = "swing"


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class AppConfig(BaseModel):
    trade_mode: TradeMode = TradeMode.PAPER
    strategy_mode: StrategyMode = StrategyMode.SCALP
    instrument_type: InstrumentType = InstrumentType.SWAP
    auto_invest: bool = False
    max_positions: int = 5
    order_size_usdt: float = 50.0
    leverage: int = 3
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 3.0
    trailing_stop: bool = True
    allow_short: bool = True
    scan_symbols: list[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    min_score: float = 55.0
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""
    okx_flag: str = "1"


class Position(BaseModel):
    id: str
    inst_id: str
    side: PositionSide
    quantity: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_high: float = 0.0
    strategy_mode: StrategyMode = StrategyMode.SCALP
    instrument_type: InstrumentType = InstrumentType.SWAP
    entry_reason: str = ""
    entry_score: float = 0.0
    opened_at: str = ""
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


class TradeRecord(BaseModel):
    id: str
    inst_id: str
    side: str
    quantity: float
    price: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""
    mode: TradeMode = TradeMode.PAPER
    ts: str = ""


class CoinCandidate(BaseModel):
    inst_id: str
    last_price: float
    change_24h_pct: float
    volume_24h_usdt: float
    score: float = 0.0
    scalp_ok: bool = False
    swing_ok: bool = False
    outlook: str = ""
    reasons: list[str] = Field(default_factory=list)
    rsi: float = 50.0
    trend: str = ""


class BotStatus(BaseModel):
    running: bool = False
    phase: str = "idle"
    last_scan: Optional[str] = None
    scan_count: int = 0
    message: str = ""


class BotState(BaseModel):
    status: BotStatus = Field(default_factory=BotStatus)
    activity_log: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioSnapshot(BaseModel):
    balance: float
    equity: float
    available: float
    unrealized_pnl: float
    realized_pnl: float
    positions: list[Position]
    trade_count: int
    win_rate: float = 0.0


class StatusResponse(BaseModel):
    build: str = OAT_BUILD
    config: AppConfig
    bot: BotState
    portfolio: PortfolioSnapshot
    candidates: list[CoinCandidate] = Field(default_factory=list)
    linked: bool = False
    link_message: str = ""


class BotStartRequest(BaseModel):
    auto_invest: Optional[bool] = None
    strategy_mode: Optional[StrategyMode] = None


class ManualOrderRequest(BaseModel):
    inst_id: str
    side: PositionSide
    size_usdt: float = 50.0
    leverage: int = 3


class ConfigUpdateRequest(BaseModel):
    config: AppConfig


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
