"""Backtest result models."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BacktestLogEntry(BaseModel):
    ts: str
    level: str = "info"
    message: str


class BacktestTrade(BaseModel):
    inst_id: str
    side: str
    strategy: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    score: float
    sl_pct: float
    tp_pct: float
    notional_usdt: float = 0.0
    margin_usdt: float = 0.0
    fee_usdt: float = 0.0
    pnl_usdt: float
    pnl_pct: float
    exit_reason: str


class BacktestScoreTrial(BaseModel):
    min_score: float
    total_pnl: float
    win_rate: float
    trades: int
    long_entries: int
    short_entries: int


class BacktestDirectionTrial(BaseModel):
    mode: str
    window_ratio: float
    min_score: float
    total_pnl: float
    win_rate: float
    trades: int
    long_trades: int = 0
    short_trades: int = 0


class BacktestSlTpTrial(BaseModel):
    stop_loss_pct: float
    take_profit_pct: float
    total_pnl: float
    win_rate: float
    trades: int
    tp_hits: int = 0
    sl_hits: int = 0


class BacktestRecommendation(BaseModel):
    min_score: float
    reason: str
    trials: list[BacktestScoreTrial] = Field(default_factory=list)
    direction: str = "normal"
    direction_reason: str = ""
    direction_trials: list[BacktestDirectionTrial] = Field(default_factory=list)
    window_ratio: float = 1.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    sl_tp_reason: str = ""
    sl_tp_trials: list[BacktestSlTpTrial] = Field(default_factory=list)


class SymbolCandleChart(BaseModel):
    bars: list[dict[str, float]] = Field(default_factory=list)
    total_bars: int = 0
    display_offset: int = 0
    trade_markers: list[dict[str, int]] = Field(default_factory=list)


class BacktestMetrics(BaseModel):
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    long_trades: int = 0
    short_trades: int = 0
    avg_score_entries: float = 0.0
    max_drawdown_pct: float = 0.0
    bars_evaluated: int = 0
    start_equity: float = 0.0
    end_equity: float = 0.0
    order_notional_usdt: float = 0.0
    total_fees_usdt: float = 0.0


class BacktestResult(BaseModel):
    id: str
    status: str
    started_at: str
    finished_at: str = ""
    strategy_mode: str
    symbols: list[str] = Field(default_factory=list)
    candle_bars: int = 0
    candle_interval: str = "5m"
    symbol_charts: dict[str, SymbolCandleChart] = Field(default_factory=dict)
    params_snapshot: dict[str, Any] = Field(default_factory=dict)
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    recommendation: Optional[BacktestRecommendation] = None
    trades: list[BacktestTrade] = Field(default_factory=list)
    logs: list[BacktestLogEntry] = Field(default_factory=list)
    error: str = ""
    symbol_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BacktestStatus(BaseModel):
    running: bool = False
    progress_pct: float = 0.0
    phase: str = "idle"
    message: str = ""
    result_id: str = ""
