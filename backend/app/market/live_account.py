"""Sync live portfolio from OKX account balance and positions."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.market.okx_client import get_okx_client
from app.models import AppConfig, InstrumentType, Position, PositionSide, StrategyMode, utc_now_iso
from app.strategy_utils import sl_tp_pcts  # used for pct placeholders until dynamic refresh

logger = logging.getLogger("oat.live_account")

_STABLE = frozenset({"USDT", "USD", "USDC"})


def _inst_type(config: AppConfig) -> str:
    if config.instrument_type == InstrumentType.SPOT:
        return "SPOT"
    if config.instrument_type == InstrumentType.FUTURES:
        return "FUTURES"
    return "SWAP"


def _parse_usd_balance(rows: list) -> tuple[float, float]:
    """Return (equity_usd, available_usd) from get_account_balance data."""
    if not rows:
        return 0.0, 0.0
    acct = rows[0]
    equity = float(acct.get("totalEq") or acct.get("adjEq") or 0)

    avail = float(acct.get("availEq") or 0)
    if avail <= 0:
        for d in acct.get("details") or []:
            ccy = (d.get("ccy") or "").upper()
            if ccy in _STABLE:
                avail += float(d.get("availEq") or d.get("cashBal") or 0)
    if avail <= 0 and equity > 0:
        avail = equity

    return round(equity, 2), round(avail, 2)


def _resolve_strategy(strategy: StrategyMode | str) -> StrategyMode:
    if isinstance(strategy, StrategyMode):
        s = strategy
    else:
        try:
            s = StrategyMode(str(strategy))
        except ValueError:
            s = StrategyMode.SCALP
    if s == StrategyMode.BOTH:
        return StrategyMode.SCALP
    return s


def _sl_tp(
    entry: float,
    side: PositionSide,
    config: AppConfig,
    strategy: StrategyMode | str,
) -> tuple[float, float]:
    if entry <= 0:
        return 0.0, 0.0
    strat = _resolve_strategy(strategy)
    sl_pct, tp_pct = sl_tp_pcts(config, strat)
    sl_r = sl_pct / 100
    tp_r = tp_pct / 100
    if side == PositionSide.LONG:
        return entry * (1 - sl_r), entry * (1 + tp_r)
    return entry * (1 + sl_r), entry * (1 - tp_r)


def _okx_to_position(raw: dict, config: AppConfig, existing: Optional[Position]) -> Optional[Position]:
    inst_id = raw.get("instId") or ""
    if not inst_id:
        return None

    try:
        size = abs(float(raw.get("pos") or 0))
    except (TypeError, ValueError):
        size = 0.0
    if size <= 0:
        return None

    pos_side = (raw.get("posSide") or "long").lower()
    side = PositionSide.SHORT if pos_side == "short" else PositionSide.LONG

    entry = float(raw.get("avgPx") or raw.get("nonSettleAvgPx") or 0)
    mark = float(raw.get("markPx") or raw.get("last") or entry)
    upl = float(raw.get("upl") or 0)
    upl_ratio = float(raw.get("uplRatio") or 0) * 100
    lever = int(float(raw.get("lever") or config.leverage or 1))

    if existing:
        reason, score, strategy, opened = (
            existing.entry_reason,
            existing.entry_score,
            existing.strategy_mode,
            existing.opened_at,
        )
        pos_id = existing.id
        auto_disabled = existing.auto_sl_tp_disabled
        manual = existing.sl_tp_manual
        manual_sl = existing.stop_loss
        manual_tp = existing.take_profit
        manual_sl_pct = existing.sl_pct
        manual_tp_pct = existing.tp_pct
        manual_note = existing.sl_tp_note
    else:
        reason, score = "OKX 포지션", 0.0
        strategy = (
            StrategyMode.SCALP
            if config.strategy_mode == StrategyMode.BOTH
            else config.strategy_mode
        )
        opened = utc_now_iso()
        pos_id = str(uuid.uuid4())[:8]
        auto_disabled = False
        manual = False
        manual_sl = manual_tp = manual_sl_pct = manual_tp_pct = 0.0
        manual_note = "OKX동기화·차트갱신예정"

    sl, tp = _sl_tp(entry, side, config, strategy)
    sl_p, tp_p = sl_tp_pcts(config, _resolve_strategy(strategy))
    if manual or auto_disabled:
        sl = manual_sl or sl
        tp = manual_tp or tp
        sl_p = manual_sl_pct or sl_p
        tp_p = manual_tp_pct or tp_p

    cost = entry * size if entry > 0 else 0
    if upl_ratio == 0 and cost > 0:
        upl_ratio = upl / cost * 100

    return Position(
        id=pos_id,
        inst_id=inst_id,
        side=side,
        quantity=size,
        entry_price=entry,
        current_price=mark,
        stop_loss=sl,
        take_profit=tp,
        sl_pct=sl_p,
        tp_pct=tp_p,
        sl_tp_note=manual_note,
        sl_tp_manual=manual,
        auto_sl_tp_disabled=auto_disabled,
        trailing_high=mark,
        strategy_mode=strategy,
        instrument_type=config.instrument_type,
        entry_reason=reason,
        entry_score=score,
        opened_at=opened,
        leverage=lever,
        unrealized_pnl=round(upl, 4),
        unrealized_pnl_pct=round(upl_ratio, 2),
    )


def sync_live_portfolio(portfolio, config: AppConfig) -> tuple[bool, str]:
    """Overwrite live portfolio balances and positions from OKX."""
    client = get_okx_client(
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_passphrase,
        config.okx_flag,
    )
    if not client.has_credentials:
        return False, "API 키 없음"

    bal_rows = client.get_balance()
    if not bal_rows:
        return False, "OKX 잔고 조회 실패"

    equity, available = _parse_usd_balance(bal_rows)
    inst_type = _inst_type(config)
    raw_positions = client.get_positions(inst_type=inst_type)

    new_positions: dict[str, Position] = {}
    unrealized = 0.0
    for raw in raw_positions:
        inst_id = raw.get("instId") or ""
        existing = portfolio.positions.get(inst_id)
        pos = _okx_to_position(raw, config, existing)
        if pos:
            new_positions[inst_id] = pos
            unrealized += pos.unrealized_pnl

    portfolio.balance = equity
    portfolio.available = available
    portfolio.positions = new_positions
    portfolio.save()

    env = "데모" if config.okx_flag == "1" else "실거래"
    return True, (
        f"OKX {env} 연동 — Equity ${equity:,.2f} / 가용 ${available:,.2f} "
        f"(포지션 {len(new_positions)}개)"
    )
