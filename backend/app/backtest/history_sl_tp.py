"""SL/TP suggestions from accumulated backtest history."""

from __future__ import annotations

from typing import Any


def exit_stats_from_trades(trades: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"sl": 0, "tp": 0, "end_close": 0, "trailing": 0, "other": 0}
    for t in trades:
        reason = str(t.get("exit_reason") or "")
        if "손절" in reason:
            stats["sl"] += 1
        elif "익절" in reason:
            stats["tp"] += 1
        elif "종료 청산" in reason:
            stats["end_close"] += 1
        elif "트레일링" in reason:
            stats["trailing"] += 1
        else:
            stats["other"] += 1
    return stats


def _clamp_sl(sl: float) -> float:
    return round(max(0.5, min(8.0, sl)), 2)


def _clamp_tp(tp: float) -> float:
    return round(max(0.8, min(15.0, tp)), 2)


def merge_sl_tp_with_history(
    grid_sl: float,
    grid_tp: float,
    history: list[dict[str, Any]],
    *,
    use_history: bool,
) -> tuple[float, float, str]:
    """Blend grid-search SL/TP with win-rate-weighted history."""
    grid_sl = _clamp_sl(grid_sl)
    grid_tp = _clamp_tp(grid_tp)
    if not use_history or not history:
        return grid_sl, grid_tp, f"그리드 SL {grid_sl}% / TP {grid_tp}%"

    good = [
        e
        for e in history
        if e.get("status") == "done"
        and (e.get("metrics") or {}).get("trade_count", 0) >= 2
    ]
    if not good:
        return grid_sl, grid_tp, f"그리드 SL {grid_sl}% / TP {grid_tp}% (이력 부족)"

    w_sl = w_tp = total_w = 0.0
    end_close_total = 0
    trade_total = 0
    for e in good[:40]:
        rec = e.get("recommendation") or {}
        sl = rec.get("stop_loss_pct") or e.get("applied_sl_pct")
        tp = rec.get("take_profit_pct") or e.get("applied_tp_pct")
        if sl is None or tp is None:
            continue
        metrics = e.get("metrics") or {}
        wr = float(metrics.get("win_rate") or 0)
        tc = int(metrics.get("trade_count") or 0)
        w = max(1.0, wr) * min(tc, 25)
        w_sl += float(sl) * w
        w_tp += float(tp) * w
        total_w += w
        ex = e.get("exit_stats") or {}
        end_close_total += int(ex.get("end_close") or 0)
        trade_total += tc

    if total_w <= 0:
        return grid_sl, grid_tp, f"그리드 SL {grid_sl}% / TP {grid_tp}%"

    hist_sl = _clamp_sl(w_sl / total_w)
    hist_tp = _clamp_tp(w_tp / total_w)
    final_sl = _clamp_sl(grid_sl * 0.65 + hist_sl * 0.35)
    final_tp = _clamp_tp(grid_tp * 0.65 + hist_tp * 0.35)

    notes = [f"그리드 {grid_sl}/{grid_tp}%", f"이력({len(good)}회) {hist_sl}/{hist_tp}%"]
    if trade_total > 0 and end_close_total / trade_total > 0.35:
        final_tp = _clamp_tp(final_tp * 0.88)
        notes.append("미청산 비율 높음 → TP 소폭 축소")

    return final_sl, final_tp, " · ".join(notes) + f" → SL {final_sl}% TP {final_tp}%"
