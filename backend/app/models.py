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
    BOTH = "both"


class PositionSideMode(str, Enum):
    AUTO = "auto"
    LONG = "long"
    SHORT = "short"


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
    position_size_mode: str = "fixed"
    order_size_pct: float = 2.0
    max_order_size_usdt: float = 0.0
    min_order_size_usdt: float = 0.0
    size_split_slots: bool = False
    order_size_basis: str = "notional"
    leverage: int = 3
    margin_mode: str = "isolated"
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 3.0
    trailing_stop: bool = True
    allow_short: bool = True
    position_side: PositionSideMode = PositionSideMode.AUTO
    scan_symbols: list[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    min_score: float = 55.0
    backtest_auto_settings: bool = False
    backtest_auto_sl_tp: bool = False
    trend_scale_in: bool = True
    max_scale_ins: int = Field(default=2, ge=0, le=5)
    scale_in_size_pct: float = Field(default=50.0, ge=5.0, le=100.0)
    scale_in_min_pnl_pct: float = Field(default=3.0, ge=0.0, le=100.0)
    trend_exit_confirm_bars: int = Field(default=3, ge=1, le=6)
    backtest_interval_minutes: int = Field(default=60, ge=1, le=1440)
    backtest_candle_limit: int = Field(default=500, ge=80, le=1000)
    paper_initial_balance: float = Field(default=10_000.0, gt=0)
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
    sl_pct: float = 0.0
    tp_pct: float = 0.0
    sl_usdt: float = 0.0
    tp_usdt: float = 0.0
    sl_tp_note: str = ""
    sl_tp_manual: bool = False
    auto_sl_tp_disabled: bool = False
    auto_sl_disabled: bool = False
    auto_tp_disabled: bool = False
    trailing_high: float = 0.0
    strategy_mode: StrategyMode = StrategyMode.SCALP
    instrument_type: InstrumentType = InstrumentType.SWAP
    entry_reason: str = ""
    entry_score: float = 0.0
    opened_at: str = ""
    leverage: int = 0
    notional_usdt: float = 0.0
    liquidation_price: float = 0.0
    scale_in_count: int = 0
    last_scale_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


class PendingOrder(BaseModel):
    inst_id: str
    ord_id: str = ""
    side: str = ""
    pos_side: str = ""
    order_type: str = ""
    price: float = 0.0
    size: float = 0.0
    filled_size: float = 0.0
    state: str = ""
    ts: str = ""


class TradeRecord(BaseModel):
    id: str
    inst_id: str
    side: str
    quantity: float
    price: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""
    close_type: str = ""
    position_side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    notional_usdt: float = 0.0
    strategy_mode: str = ""
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
    short_scalp_ok: bool = False
    short_swing_ok: bool = False
    outlook: str = ""
    reasons: list[str] = Field(default_factory=list)
    rsi: float = 50.0
    trend: str = ""
    sparkline: list[float] = Field(default_factory=list)
    ohlc_bars: list[dict[str, float]] = Field(default_factory=list)


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
    position_side: Optional[PositionSideMode] = None


class ManualOrderRequest(BaseModel):
    inst_id: str
    side: PositionSide
    size_usdt: float = 50.0
    leverage: int = 3
    order_type: str = "market"
    price: float = 0.0


class ConfigUpdateRequest(BaseModel):
    config: AppConfig


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
