"""Sync live portfolio from OKX account balance, positions, and fills."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.market.okx_client import get_okx_client
from app.contract_sizing import swap_margin_usdt, swap_notional_usdt
from app.market.instrument_rules import swap_sizing_rules
from app.models import (
    AppConfig,
    InstrumentType,
    Position,
    PositionSide,
    StrategyMode,
    TradeRecord,
    utc_now_iso,
)
from app.strategy_utils import sl_tp_pcts
from app.sl_tp_utils import pnl_pct_to_price_pct

logger = logging.getLogger("oat.live_account")

_STABLE = frozenset({"USDT", "USD", "USDC"})
_last_fills_sync = 0.0


def _inst_type(config: AppConfig) -> str:
    if config.instrument_type == InstrumentType.SPOT:
        return "SPOT"
    if config.instrument_type == InstrumentType.FUTURES:
        return "FUTURES"
    return "SWAP"


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


def _abs_float(value) -> float:
    return abs(_float(value))


def _parse_usd_balance(rows: list) -> tuple[float, float]:
    if not rows:
        return 0.0, 0.0
    acct = rows[0]
    equity = _float(acct.get("totalEq") or acct.get("adjEq"))

    avail = _float(acct.get("availEq"))
    if avail <= 0:
        for d in acct.get("details") or []:
            ccy = (d.get("ccy") or "").upper()
            if ccy in _STABLE:
                avail += _float(d.get("availEq") or d.get("cashBal"))
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
    return StrategyMode.SCALP if s == StrategyMode.BOTH else s


def _side_from_okx(raw: dict) -> PositionSide:
    raw_pos = _float(raw.get("pos"))
    pos_side = (raw.get("posSide") or "").lower()
    if pos_side == "short" or raw_pos < 0:
        return PositionSide.SHORT
    return PositionSide.LONG


def _sl_tp(
    entry: float,
    side: PositionSide,
    config: AppConfig,
    strategy: StrategyMode | str,
    leverage: int = 1,
) -> tuple[float, float]:
    if entry <= 0:
        return 0.0, 0.0
    strat = _resolve_strategy(strategy)
    sl_pct, tp_pct = sl_tp_pcts(config, strat)
    sl_r = pnl_pct_to_price_pct(sl_pct, leverage, config.instrument_type) / 100
    tp_r = pnl_pct_to_price_pct(tp_pct, leverage, config.instrument_type) / 100
    if side == PositionSide.LONG:
        return entry * (1 - sl_r), entry * (1 + tp_r)
    return entry * (1 + sl_r), entry * (1 - tp_r)


def _okx_to_position(
    raw: dict,
    config: AppConfig,
    existing: Optional[Position],
) -> Optional[Position]:
    inst_id = raw.get("instId") or ""
    if not inst_id:
        return None

    raw_size = _float(raw.get("pos"))
    size = abs(raw_size)
    if size <= 0:
        return None

    side = _side_from_okx(raw)
    entry = _float(raw.get("avgPx") or raw.get("nonSettleAvgPx"))
    mark = _float(raw.get("markPx") or raw.get("last") or entry)
    liq = _float(raw.get("liqPx"))
    upl = _float(raw.get("upl"))
    upl_ratio = _float(raw.get("uplRatio")) * 100
    lever = int(_float(raw.get("lever"), config.leverage or 1))
    notional_usdt = _abs_float(
        raw.get("notionalUsd")
        or raw.get("notionalUsdForBorrow")
        or raw.get("notionalUsdForSwap")
    )

    if existing:
        reason = existing.entry_reason
        score = existing.entry_score
        strategy = existing.strategy_mode
        opened = existing.opened_at
        pos_id = existing.id
        auto_disabled = existing.auto_sl_tp_disabled
        sl_disabled = existing.auto_sl_disabled
        tp_disabled = existing.auto_tp_disabled
        profit_protect_disabled = existing.auto_profit_protect_disabled
        manual = existing.sl_tp_manual
        manual_sl = existing.stop_loss
        manual_tp = existing.take_profit
        manual_sl_pct = existing.sl_pct
        manual_tp_pct = existing.tp_pct
        manual_sl_usdt = existing.sl_usdt
        manual_tp_usdt = existing.tp_usdt
        manual_note = existing.sl_tp_note
        scale_in_count = existing.scale_in_count
        last_scale_price = existing.last_scale_price
    else:
        reason, score = "OKX 포지션 동기화", 0.0
        strategy = (
            StrategyMode.SCALP
            if config.strategy_mode == StrategyMode.BOTH
            else config.strategy_mode
        )
        opened = utc_now_iso()
        pos_id = str(uuid.uuid4())[:8]
        auto_disabled = False
        sl_disabled = False
        tp_disabled = False
        profit_protect_disabled = False
        manual = False
        manual_sl = manual_tp = manual_sl_pct = manual_tp_pct = 0.0
        manual_sl_usdt = manual_tp_usdt = 0.0
        scale_in_count = 0
        last_scale_price = entry
        manual_note = "OKX 동기화"

    sl, tp = _sl_tp(entry, side, config, strategy, lever)
    sl_p, tp_p = sl_tp_pcts(config, _resolve_strategy(strategy))
    if manual or auto_disabled:
        sl = manual_sl or sl
        tp = manual_tp or tp
        sl_p = manual_sl_pct or sl_p
        tp_p = manual_tp_pct or tp_p

    cost = notional_usdt if notional_usdt > 0 else (entry * size if entry > 0 else 0)
    if config.instrument_type != InstrumentType.SPOT:
        pct_base = swap_margin_usdt(cost, lever)
    else:
        pct_base = cost
    if upl_ratio == 0 and pct_base > 0:
        upl_ratio = upl / pct_base * 100

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
        sl_usdt=manual_sl_usdt,
        tp_usdt=manual_tp_usdt,
        sl_tp_note=manual_note,
        sl_tp_manual=manual,
        auto_sl_tp_disabled=auto_disabled,
        auto_sl_disabled=sl_disabled,
        auto_tp_disabled=tp_disabled,
        auto_profit_protect_disabled=profit_protect_disabled,
        trailing_high=mark,
        strategy_mode=strategy,
        instrument_type=config.instrument_type,
        entry_reason=reason,
        entry_score=score,
        opened_at=opened,
        leverage=lever,
        notional_usdt=round(notional_usdt, 2),
        liquidation_price=liq,
        scale_in_count=scale_in_count,
        last_scale_price=last_scale_price or entry,
        unrealized_pnl=round(upl, 4),
        unrealized_pnl_pct=round(upl_ratio, 2),
    )


def _ts_to_iso(ts: str) -> str:
    try:
        return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).isoformat()
    except Exception:
        return utc_now_iso()


def _iso_to_ms(value: str) -> int:
    if not value:
        return 0
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _fill_notional_usdt(raw: dict, config: AppConfig, inst_id: str, px: float, qty: float) -> float:
    notional = _abs_float(raw.get("fillNotionalUsd") or raw.get("notionalUsd"))
    if notional > 0:
        return notional
    if px <= 0 or qty <= 0:
        return 0.0
    if config.instrument_type != InstrumentType.SPOT:
        try:
            rules = swap_sizing_rules(config, inst_id)
            return swap_notional_usdt(qty, px, rules.ct_val)
        except Exception:
            return 0.0
    return px * qty


def _looks_like_existing_close(
    portfolio,
    inst_id: str,
    side: str,
    pos_side: str,
    px: float,
    qty: float,
    pnl: float,
    fill_ms: int,
) -> bool:
    if not fill_ms:
        return False
    for trade in reversed(portfolio.trades[-120:]):
        if trade.inst_id != inst_id or trade.side != side:
            continue
        if pos_side and trade.position_side and trade.position_side != pos_side:
            continue
        trade_ms = _iso_to_ms(str(trade.ts))
        if not trade_ms or abs(fill_ms - trade_ms) > 120_000:
            continue
        qty_close = qty > 0 and abs(float(trade.quantity) - qty) <= max(qty * 0.02, 1e-9)
        price_close = px > 0 and trade.price > 0 and abs(float(trade.price) - px) / px <= 0.02
        pnl_close = abs(float(trade.pnl) - pnl) <= max(abs(pnl) * 0.15, 0.01)
        if qty_close or (price_close and pnl_close):
            return True
    return False


def _sync_recent_fills(portfolio, client, config: AppConfig, force: bool = False) -> None:
    global _last_fills_sync
    now = time.monotonic()
    if not force and now - _last_fills_sync < 20:
        return
    _last_fills_sync = now
    fills = client.get_fills_history(inst_type=_inst_type(config), limit=100)
    if not fills:
        return

    existing_ids = {t.id for t in portfolio.trades}
    existing_keys = {
        f"{t.inst_id}:{t.ts}:{t.side}:{round(t.price, 12)}:{round(t.quantity, 12)}"
        for t in portfolio.trades
    }
    added: list[TradeRecord] = []
    reset_ms = _iso_to_ms(getattr(portfolio, "stats_reset_at", ""))
    for f in fills:
        fill_ms = int(_float(f.get("ts"), 0))
        if reset_ms and fill_ms and fill_ms <= reset_ms:
            continue

        signed_pnl = _float(f.get("fillPnl") or f.get("pnl"))
        if signed_pnl == 0:
            continue

        inst_id = f.get("instId") or ""
        side = (f.get("side") or "").lower()
        px = _abs_float(f.get("fillPx") or f.get("px") or f.get("avgPx"))
        qty = _abs_float(f.get("fillSz") or f.get("sz"))
        ts = _ts_to_iso(str(f.get("ts") or ""))
        tid = str(f.get("fillId") or f.get("tradeId") or f.get("ordId") or "")[:32]
        if not tid:
            tid = f"okx-{abs(hash((inst_id, ts, side, px, qty))) % 10_000_000}"

        key = f"{inst_id}:{ts}:{side}:{round(px, 12)}:{round(qty, 12)}"
        if tid in existing_ids or key in existing_keys:
            continue

        pos_side_raw = (f.get("posSide") or "").lower()
        if pos_side_raw in ("long", "short"):
            pos_side = pos_side_raw
        else:
            pos_side = "long" if side == "sell" else "short"
        if _looks_like_existing_close(portfolio, inst_id, side, pos_side, px, qty, signed_pnl, fill_ms):
            continue
        notional = _fill_notional_usdt(f, config, inst_id, px, qty)
        if config.instrument_type != InstrumentType.SPOT:
            pct_base = swap_margin_usdt(notional, config.leverage)
        else:
            pct_base = notional
        pnl_pct = signed_pnl / pct_base * 100 if pct_base > 0 else 0.0
        added.append(
            TradeRecord(
                id=tid,
                inst_id=inst_id,
                side=side,
                quantity=qty,
                price=px,
                pnl=round(signed_pnl, 4),
                pnl_pct=round(pnl_pct, 2),
                reason="OKX 체결 내역 동기화",
                close_type="tp" if signed_pnl > 0 else "sl",
                position_side=pos_side,
                exit_price=px,
                notional_usdt=round(notional, 2),
                mode=config.trade_mode,
                ts=ts,
            )
        )
        existing_ids.add(tid)
        existing_keys.add(key)

    if added:
        portfolio.trades.extend(reversed(added))
        portfolio.trades = portfolio.trades[-500:]


def sync_live_portfolio(
    portfolio,
    config: AppConfig,
    include_fills: bool = True,
) -> tuple[bool, str]:
    """Overwrite live balances/positions from OKX and merge recent close fills."""
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
    if include_fills:
        _sync_recent_fills(portfolio, client, config)

    new_positions: dict[str, Position] = {}
    for raw in raw_positions:
        inst_id = raw.get("instId") or ""
        existing = portfolio.positions.get(inst_id)
        pos = _okx_to_position(raw, config, existing)
        if pos:
            new_positions[inst_id] = pos

    portfolio.balance = equity
    portfolio.available = available
    portfolio.positions = new_positions
    portfolio.save()

    env = "모의" if config.okx_flag == "1" else "실거래"
    return True, (
        f"OKX {env} 연동 - Equity ${equity:,.2f} / 가능 ${available:,.2f} "
        f"(포지션 {len(new_positions)}개)"
    )
