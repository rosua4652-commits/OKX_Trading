"""Per-symbol SL/TP profiles from backtest — used in live auto-trading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.backtest.engine import (
    SL_GRID,
    TP_GRID,
    _count_exit_types,
    _sl_tp_rank,
    run_simulation,
)
from app.backtest.models import BacktestLogEntry, BacktestTrade
from app.models import AppConfig, PositionSide, StrategyMode, utc_now_iso
from app.sl_tp_utils import pnl_pct_to_price_pct

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PROFILES_FILE = DATA_DIR / "symbol_sl_tp_profiles.json"


class SymbolSlTpProfile(BaseModel):
    inst_id: str
    stop_loss_pct: float
    take_profit_pct: float
    win_rate: float = 0.0
    trades: int = 0
    tp_hits: int = 0
    sl_hits: int = 0
    avg_win_tp_pct: float = 0.0
    updated_at: str = ""
    run_id: str = ""


def _clamp_sl(v: float) -> float:
    return round(max(0.5, min(8.0, v)), 2)


def _clamp_tp(v: float) -> float:
    return round(max(0.8, min(12.0, v)), 2)


def _avg_win_tp_from_trades(trades: list[BacktestTrade]) -> float | None:
    wins = [t for t in trades if t.pnl_usdt > 0 and "익절" in t.exit_reason]
    if not wins:
        return None
    return round(sum(t.tp_pct for t in wins) / len(wins), 2)


def optimize_symbol_sl_tp(
    inst_id: str,
    candles: list[list],
    config: AppConfig,
    min_score: float,
    invert_signals: bool,
    window_ratio: float,
    run_id: str = "",
) -> SymbolSlTpProfile | None:
    """Grid-search SL/TP for a single symbol (win-rate priority)."""
    if len(candles) < 70:
        return None

    symbol_candles = {inst_id: candles}
    base_sl = config.stop_loss_pct or 2.0
    base_tp = config.take_profit_pct or 3.0
    sl_candidates = sorted(
        set(SL_GRID + [round(base_sl * 0.75, 2), round(base_sl, 2), round(base_sl * 1.25, 2)])
    )
    tp_candidates = sorted(
        set(TP_GRID + [round(base_tp * 0.75, 2), round(base_tp, 2), round(base_tp * 1.25, 2), 1.5])
    )

    best_rank = float("-inf")
    best_sl, best_tp = base_sl, base_tp
    best_wr, best_trades, best_tp_h, best_sl_h = 0.0, 0, 0, 0
    best_trades_list: list[BacktestTrade] = []

    for sl in sl_candidates:
        for tp in tp_candidates:
            if tp < sl * 0.55:
                continue
            cfg = config.model_copy(deep=True)
            cfg.stop_loss_pct = sl
            cfg.take_profit_pct = tp
            state, _ = run_simulation(
                cfg,
                symbol_candles,
                [],
                min_score_override=min_score,
                invert_signals=invert_signals,
                window_ratio=window_ratio,
            )
            sym_trades = [t for t in state.trades if t.inst_id == inst_id]
            if len(sym_trades) < 1:
                continue
            pnl = sum(t.pnl_usdt for t in sym_trades)
            wins = sum(1 for t in sym_trades if t.pnl_usdt > 0)
            wr = wins / len(sym_trades) * 100
            sl_h, tp_h = _count_exit_types(sym_trades)
            rank = _sl_tp_rank(wr, pnl, len(sym_trades), tp_h)
            if rank > best_rank:
                best_rank = rank
                best_sl, best_tp = sl, tp
                best_wr, best_trades = wr, len(sym_trades)
                best_tp_h, best_sl_h = tp_h, sl_h
                best_trades_list = sym_trades

    if best_trades < 1:
        return None

    avg_win_tp = _avg_win_tp_from_trades(best_trades_list)
    final_tp = best_tp
    if avg_win_tp is not None and avg_win_tp > 0:
        final_tp = _clamp_tp(best_tp * 0.45 + avg_win_tp * 0.55)

    return SymbolSlTpProfile(
        inst_id=inst_id,
        stop_loss_pct=_clamp_sl(best_sl),
        take_profit_pct=final_tp,
        win_rate=round(best_wr, 1),
        trades=best_trades,
        tp_hits=best_tp_h,
        sl_hits=best_sl_h,
        avg_win_tp_pct=avg_win_tp or 0.0,
        updated_at=utc_now_iso(),
        run_id=run_id,
    )


def build_symbol_profiles(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    trades: list[BacktestTrade],
    min_score: float,
    invert_signals: bool,
    window_ratio: float,
    run_id: str = "",
) -> dict[str, SymbolSlTpProfile]:
    profiles: dict[str, SymbolSlTpProfile] = {}
    for inst_id, candles in symbol_candles.items():
        prof = optimize_symbol_sl_tp(
            inst_id,
            candles,
            config,
            min_score,
            invert_signals,
            window_ratio,
            run_id,
        )
        if prof:
            profiles[inst_id] = prof

    # Symbols with trades but no grid result — infer from winning exits
    for inst_id in {t.inst_id for t in trades}:
        if inst_id in profiles:
            continue
        sym_trades = [t for t in trades if t.inst_id == inst_id]
        if len(sym_trades) < 1:
            continue
        wins = [t for t in sym_trades if t.pnl_usdt > 0]
        avg_win_tp = _avg_win_tp_from_trades(sym_trades)
        sl_vals = [t.sl_pct for t in sym_trades if t.sl_pct > 0]
        tp_vals = [t.tp_pct for t in sym_trades if t.tp_pct > 0]
        profiles[inst_id] = SymbolSlTpProfile(
            inst_id=inst_id,
            stop_loss_pct=_clamp_sl(sum(sl_vals) / len(sl_vals) if sl_vals else config.stop_loss_pct),
            take_profit_pct=_clamp_tp(
                avg_win_tp
                if avg_win_tp
                else (sum(tp_vals) / len(tp_vals) if tp_vals else config.take_profit_pct)
            ),
            win_rate=round(len(wins) / len(sym_trades) * 100, 1),
            trades=len(sym_trades),
            updated_at=utc_now_iso(),
            run_id=run_id,
        )
    return profiles


def load_profiles() -> dict[str, SymbolSlTpProfile]:
    if not PROFILES_FILE.exists():
        return {}
    try:
        raw = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        return {k: SymbolSlTpProfile(**v) for k, v in raw.items()}
    except Exception:
        return {}


def save_profiles(profiles: dict[str, SymbolSlTpProfile]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: v.model_dump() for k, v in profiles.items()}
    PROFILES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_profiles(
    existing: dict[str, SymbolSlTpProfile],
    incoming: dict[str, SymbolSlTpProfile],
) -> dict[str, SymbolSlTpProfile]:
    out = dict(existing)
    for inst_id, new in incoming.items():
        old = out.get(inst_id)
        if old is None or old.trades < 2:
            out[inst_id] = new
            continue
        w_old = max(1.0, old.win_rate) * min(old.trades, 20)
        w_new = max(1.0, new.win_rate) * min(new.trades, 20)
        total = w_old + w_new
        out[inst_id] = SymbolSlTpProfile(
            inst_id=inst_id,
            stop_loss_pct=_clamp_sl(
                (old.stop_loss_pct * w_old + new.stop_loss_pct * w_new) / total
            ),
            take_profit_pct=_clamp_tp(
                (old.take_profit_pct * w_old + new.take_profit_pct * w_new) / total
            ),
            win_rate=round((old.win_rate * w_old + new.win_rate * w_new) / total, 1),
            trades=old.trades + new.trades,
            tp_hits=old.tp_hits + new.tp_hits,
            sl_hits=old.sl_hits + new.sl_hits,
            avg_win_tp_pct=new.avg_win_tp_pct or old.avg_win_tp_pct,
            updated_at=new.updated_at,
            run_id=new.run_id,
        )
    return out


def persist_profiles_from_backtest(
    profiles: dict[str, SymbolSlTpProfile],
) -> dict[str, SymbolSlTpProfile]:
    merged = merge_profiles(load_profiles(), profiles)
    save_profiles(merged)
    return merged


def get_symbol_profile(inst_id: str) -> SymbolSlTpProfile | None:
    return load_profiles().get(inst_id)


def resolve_entry_sl_tp(
    inst_id: str,
    config: AppConfig,
    strategy: StrategyMode,
) -> tuple[float, float, str] | None:
    """Return (sl_pct, tp_pct, method) when backtest auto SL/TP is enabled."""
    if not config.backtest_auto_sl_tp:
        return None

    prof = get_symbol_profile(inst_id)
    if prof and prof.trades >= 1:
        note = f"백테스트 {inst_id.split('-')[0]} SL {prof.stop_loss_pct}% TP {prof.take_profit_pct}%"
        note += f" (승률 {prof.win_rate}%·{prof.trades}건"
        if prof.avg_win_tp_pct > 0:
            note += f"·익절평균 {prof.avg_win_tp_pct}%"
        note += ")"
        return prof.stop_loss_pct, prof.take_profit_pct, note

    from app.strategy_utils import sl_tp_pcts

    sl, tp = sl_tp_pcts(config, strategy)
    return sl, tp, "백테스트 전역 SL/TP"


def plan_prices(
    entry: float,
    side: PositionSide,
    sl_pct: float,
    tp_pct: float,
    leverage: int = 1,
) -> tuple[float, float]:
    sl_price_pct = pnl_pct_to_price_pct(sl_pct, leverage, "swap")
    tp_price_pct = pnl_pct_to_price_pct(tp_pct, leverage, "swap")
    if side == PositionSide.LONG:
        return entry * (1 - sl_price_pct / 100), entry * (1 + tp_price_pct / 100)
    return entry * (1 + sl_price_pct / 100), entry * (1 - tp_price_pct / 100)


def profiles_for_client() -> list[dict[str, Any]]:
    return [p.model_dump() for p in load_profiles().values()]
