"""Tests for OKX Auto Trader."""

import numpy as np
import pytest

from app.engine.exit_rules import should_exit
from app.engine.risk_manager import check_entry_allowed
from app.market.entry_analyzer import _analyze_closes, _rsi
from app.models import (
    AppConfig,
    CoinCandidate,
    PortfolioSnapshot,
    Position,
    PositionSide,
    StrategyMode,
)


def test_rsi():
    closes = np.array([100 + i * 0.5 for i in range(30)])
    rsi = _rsi(closes)
    assert 50 < rsi < 100


def test_analyze_closes_bullish():
    closes = np.array([100 + i * 0.3 for i in range(60)])
    volumes = np.array([1000 + i * 10 for i in range(60)], dtype=float)
    score, scalp_ok, swing_ok, outlook, reasons, rsi, trend, short_scalp, short_swing = (
        _analyze_closes(closes, volumes, StrategyMode.SCALP)
    )
    assert score > 30
    assert trend in ("strong_up", "up")
    assert outlook in ("long", "neutral")


def test_should_exit_stop_loss():
    config = AppConfig(stop_loss_pct=2.0, take_profit_pct=3.0)
    pos = Position(
        id="1",
        inst_id="BTC-USDT-SWAP",
        side=PositionSide.LONG,
        quantity=1,
        entry_price=100,
        current_price=97,
        stop_loss=98,
        take_profit=103,
    )
    exit_flag, reason = should_exit(pos, config)
    assert exit_flag
    assert "손절" in reason


def test_should_exit_take_profit():
    config = AppConfig(stop_loss_pct=2.0, take_profit_pct=3.0)
    pos = Position(
        id="1",
        inst_id="BTC-USDT-SWAP",
        side=PositionSide.LONG,
        quantity=1,
        entry_price=100,
        current_price=104,
        stop_loss=98,
        take_profit=103,
    )
    exit_flag, reason = should_exit(pos, config)
    assert exit_flag
    assert "익절" in reason


def test_risk_check_max_positions():
    config = AppConfig(max_positions=2, min_score=50, order_size_usdt=50)
    portfolio = PortfolioSnapshot(
        balance=10000,
        equity=10000,
        available=9000,
        unrealized_pnl=0,
        realized_pnl=0,
        positions=[
            Position(id="1", inst_id="A", side=PositionSide.LONG, quantity=1, entry_price=100),
            Position(id="2", inst_id="B", side=PositionSide.LONG, quantity=1, entry_price=100),
        ],
        trade_count=0,
    )
    cand = CoinCandidate(
        inst_id="C",
        last_price=100,
        change_24h_pct=2,
        volume_24h_usdt=1e6,
        score=70,
        scalp_ok=True,
        outlook="long",
    )
    ok, msg = check_entry_allowed(config, portfolio, cand)
    assert not ok
    assert "최대 포지션" in msg


def test_risk_check_allowed():
    config = AppConfig(max_positions=5, min_score=50, order_size_usdt=50)
    portfolio = PortfolioSnapshot(
        balance=10000,
        equity=10000,
        available=9000,
        unrealized_pnl=0,
        realized_pnl=0,
        positions=[],
        trade_count=0,
    )
    cand = CoinCandidate(
        inst_id="BTC-USDT-SWAP",
        last_price=50000,
        change_24h_pct=2,
        volume_24h_usdt=1e9,
        score=70,
        scalp_ok=True,
        outlook="long",
    )
    ok, msg = check_entry_allowed(config, portfolio, cand)
    assert ok


def test_analyze_closes_bearish_short():
    closes = np.array([100 - i * 0.4 for i in range(60)])
    volumes = np.array([1000.0] * 60)
    score, scalp_ok, swing_ok, outlook, reasons, rsi, trend, short_scalp, short_swing = (
        _analyze_closes(closes, volumes, StrategyMode.SCALP)
    )
    assert trend == "down"
    assert outlook in ("short", "neutral") or short_scalp or short_swing


def test_risk_check_short_allowed():
    from app.models import InstrumentType, PositionSideMode

    config = AppConfig(
        max_positions=5,
        min_score=50,
        order_size_usdt=50,
        allow_short=True,
        position_side=PositionSideMode.AUTO,
        instrument_type=InstrumentType.SWAP,
    )
    portfolio = PortfolioSnapshot(
        balance=10000,
        equity=10000,
        available=9000,
        unrealized_pnl=0,
        realized_pnl=0,
        positions=[],
        trade_count=0,
    )
    cand = CoinCandidate(
        inst_id="ETH-USDT-SWAP",
        last_price=3000,
        change_24h_pct=-5,
        volume_24h_usdt=1e9,
        score=55,
        scalp_ok=False,
        swing_ok=False,
        short_scalp_ok=True,
        short_swing_ok=True,
        outlook="short",
        trend="down",
        rsi=58,
    )
    ok, msg = check_entry_allowed(
        config, portfolio, cand, StrategyMode.SCALP, entry_side=PositionSide.SHORT
    )
    assert ok, msg
    assert "숏" in msg
