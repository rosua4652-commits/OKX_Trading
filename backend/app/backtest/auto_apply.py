"""Apply backtest recommendations to live AppConfig."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.backtest.models import BacktestResult
from app.models import AppConfig, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
AUTO_APPLY_HISTORY_FILE = DATA_DIR / "backtest_auto_apply_history.jsonl"


def _metrics_ok(result: BacktestResult) -> tuple[bool, str]:
    m = result.metrics
    if result.status != "done" or not result.recommendation:
        return False, "no recommendation"
    if m.trade_count < 6:
        return False, f"trade_count too low ({m.trade_count})"
    if m.total_pnl <= 0:
        return False, f"total_pnl not positive ({m.total_pnl})"
    if m.win_rate < 45:
        return False, f"win_rate too low ({m.win_rate}%)"
    if m.max_drawdown_pct < -25:
        return False, f"drawdown too high ({m.max_drawdown_pct}%)"
    z = result.zone_walkforward
    if z.samples < 24:
        return False, f"zone walk-forward samples too low ({z.samples})"
    if z.samples >= 12 and z.accuracy_pct < 48:
        return False, f"zone walk-forward accuracy too low ({z.accuracy_pct}%)"
    if z.samples >= 12 and z.false_break_pct > 38:
        return False, f"false breakout rate too high ({z.false_break_pct}%)"
    if z.samples >= 12 and z.avg_forward_r < 0.15:
        return False, f"zone forward expectancy too low ({z.avg_forward_r}R)"
    return True, "accepted"


def _clamp_score(score: float) -> float:
    return round(max(45.0, min(80.0, float(score))), 1)


def _clamp_sl_tp(sl: float, tp: float, current: AppConfig) -> tuple[float, float]:
    is_scalp = current.strategy_mode.value in ("scalp", "both")
    sl = round(max(4.0, min(10.0 if is_scalp else 12.0, float(sl))), 2)
    tp_cap = 10.0 if is_scalp else 18.0
    min_rr = 1.15 if is_scalp else 1.4
    max_rr = 1.8 if is_scalp else 2.4
    tp = round(max(sl * min_rr, min(tp_cap, float(tp))), 2)
    tp = round(min(tp, sl * max_rr), 2)
    return sl, tp


def build_config_from_backtest(current: AppConfig, result: BacktestResult) -> AppConfig | None:
    ok, _ = _metrics_ok(result)
    if not ok:
        return None

    rec = result.recommendation
    apply_score = current.backtest_auto_settings
    apply_sl_tp = current.backtest_auto_sl_tp
    if not apply_score and not apply_sl_tp:
        return None

    cfg = current.model_copy(deep=True)
    changed = False

    if apply_score:
        cfg.min_score = _clamp_score(rec.min_score)
        changed = True

    if apply_sl_tp and rec.stop_loss_pct > 0 and rec.take_profit_pct > 0:
        cfg.stop_loss_pct, cfg.take_profit_pct = _clamp_sl_tp(
            rec.stop_loss_pct,
            rec.take_profit_pct,
            current,
        )
        changed = True

    return cfg if changed else None


def config_changed(before: AppConfig, after: AppConfig) -> bool:
    return (
        before.min_score != after.min_score
        or before.position_size_mode != after.position_size_mode
        or before.order_size_pct != after.order_size_pct
        or before.stop_loss_pct != after.stop_loss_pct
        or before.take_profit_pct != after.take_profit_pct
    )


def auto_apply_decision(
    before: AppConfig,
    after: AppConfig | None,
    result: BacktestResult,
) -> dict[str, Any]:
    ok, reason = _metrics_ok(result)
    return {
        "ts": utc_now_iso(),
        "result_id": result.id,
        "accepted": bool(ok and after is not None and config_changed(before, after)),
        "reason": reason,
        "metrics": result.metrics.model_dump(),
        "zone_walkforward": result.zone_walkforward.model_dump(),
        "before": {
            "min_score": before.min_score,
            "stop_loss_pct": before.stop_loss_pct,
            "take_profit_pct": before.take_profit_pct,
            "backtest_auto_settings": before.backtest_auto_settings,
            "backtest_auto_sl_tp": before.backtest_auto_sl_tp,
        },
        "after": (
            {
                "min_score": after.min_score,
                "stop_loss_pct": after.stop_loss_pct,
                "take_profit_pct": after.take_profit_pct,
            }
            if after is not None
            else None
        ),
        "recommendation": result.recommendation.model_dump() if result.recommendation else None,
    }


def record_auto_apply_decision(decision: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with AUTO_APPLY_HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")


def get_auto_apply_history(limit: int = 30) -> list[dict[str, Any]]:
    if not AUTO_APPLY_HISTORY_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in AUTO_APPLY_HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(rows))
