"""Persist live trade feedback for later backtest tuning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import TradeRecord, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
FEEDBACK_FILE = DATA_DIR / "live_loss_feedback.jsonl"
FEEDBACK_STATE_FILE = DATA_DIR / "live_feedback_state.json"


def classify_loss_reason(
    trade: TradeRecord,
    entry: float,
    exit_price: float,
    price_move_pct: float,
) -> str:
    """
    손절 원인을 분류한다.

    - direction_error   : 방향 자체가 틀림 (롱인데 하락세, 숏인데 상승세)
    - timing_error      : 방향은 맞지만 진입 타이밍이 너무 이름 (진입 직후 바로 손절)
    - sl_too_tight      : SL이 너무 타이트해서 일시적 변동에 손절
    - sideways_entry    : 횡보장 진입으로 인한 손절
    - unknown           : 판단 불가
    """
    reason = (trade.reason or "").lower()
    side = (trade.position_side or "").lower()

    # 방향 오류: 롱인데 가격이 내려갔거나, 숏인데 가격이 올라간 경우
    if side == "long" and price_move_pct < -1.5:
        return "direction_error"
    if side == "short" and price_move_pct > 1.5:
        return "direction_error"

    # 타이밍 오류: 진입 후 빠르게 손절 (pnl_pct가 sl_pct의 80% 이상 즉시 달성)
    pnl_pct = abs(float(trade.pnl_pct or 0))
    if pnl_pct >= 1.5 and abs(price_move_pct) >= 1.0:
        # 방향은 맞는데 타이밍이 나쁜 경우
        if side == "long" and price_move_pct < 0:
            return "timing_error"
        if side == "short" and price_move_pct > 0:
            return "timing_error"

    # SL 너무 타이트: 손절 후 가격 회복 여지가 있었을 것으로 추정 (pnl_pct 작은데 손절)
    if pnl_pct < 1.0 and "손절" in (trade.reason or ""):
        return "sl_too_tight"

    # 횡보장 진입
    if abs(price_move_pct) < 0.5:
        return "sideways_entry"

    return "unknown"


def record_loss_feedback(trade: TradeRecord) -> None:
    entry = float(trade.entry_price or 0)
    exit_price = float(trade.exit_price or trade.price or 0)
    reverse_pnl = -float(trade.pnl)
    price_move_pct = 0.0
    if entry > 0 and exit_price > 0:
        price_move_pct = (exit_price - entry) / entry * 100
        if trade.position_side == "short":
            price_move_pct *= -1

    outcome = "win" if trade.pnl > 0 else "loss"
    loss_reason = None
    suggested_action = None

    if outcome == "loss":
        loss_reason = classify_loss_reason(trade, entry, exit_price, price_move_pct)

        # 원인별 대응 제안
        if loss_reason == "direction_error":
            opposite = "short" if trade.position_side == "long" else "long"
            suggested_action = f"reverse_to_{opposite}"
        elif loss_reason == "timing_error":
            suggested_action = "wait_confirmation"
        elif loss_reason == "sl_too_tight":
            suggested_action = "widen_sl"
        elif loss_reason == "sideways_entry":
            suggested_action = "skip_sideways"

    row: dict[str, Any] = {
        "ts": utc_now_iso(),
        "trade_ts": trade.ts,
        "inst_id": trade.inst_id,
        "side": trade.position_side,
        "strategy_mode": trade.strategy_mode,
        "entry_price": entry,
        "exit_price": exit_price,
        "pnl": trade.pnl,
        "pnl_pct": trade.pnl_pct,
        "notional_usdt": trade.notional_usdt,
        "reason": trade.reason,
        "outcome": outcome,
        "price_move_pct": round(price_move_pct, 6),
        "reverse_side_estimated_pnl": round(reverse_pnl, 6),
        "loss_reason": loss_reason,
        "suggested_action": suggested_action,
        "review_status": "pending_backtest",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_feedback(limit: int = 200) -> list[dict[str, Any]]:
    if not FEEDBACK_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def get_symbol_loss_reason(inst_id: str, side: str, limit: int = 10) -> str | None:
    """
    특정 종목/방향의 최근 손절 원인을 반환한다.
    재진입 판단에 활용.
    """
    rows = load_feedback(200)
    relevant = [
        r for r in reversed(rows)
        if r.get("inst_id") == inst_id
        and r.get("side") == side
        and r.get("outcome") == "loss"
        and r.get("loss_reason")
    ][:limit]
    if not relevant:
        return None
    # 가장 최근 손절 원인 반환
    return str(relevant[0].get("loss_reason") or "unknown")


def _state() -> dict[str, Any]:
    if not FEEDBACK_STATE_FILE.exists():
        return {"reviewed_count": 0, "last_reviewed_at": ""}
    try:
        return json.loads(FEEDBACK_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"reviewed_count": 0, "last_reviewed_at": ""}


def pending_feedback_summary() -> dict[str, Any]:
    rows = load_feedback(300)
    reviewed = int(_state().get("reviewed_count") or 0)
    pending = rows[reviewed:] if reviewed < len(rows) else []
    recent = rows[-30:]
    losses = [r for r in recent if r.get("outcome") == "loss"]
    wins = [r for r in recent if r.get("outcome") == "win"]
    symbols = list(dict.fromkeys(str(r.get("inst_id") or "") for r in pending if r.get("inst_id")))
    recent_win_rate = len(wins) / len(recent) * 100 if recent else 100.0

    # 원인별 집계
    reason_counts: dict[str, int] = {}
    for r in losses:
        lr = str(r.get("loss_reason") or "unknown")
        reason_counts[lr] = reason_counts.get(lr, 0) + 1

    return {
        "total_count": len(rows),
        "reviewed_count": reviewed,
        "pending_count": len(pending),
        "recent_count": len(recent),
        "recent_losses": len(losses),
        "recent_win_rate": round(recent_win_rate, 1),
        "symbols": symbols[:8],
        "loss_reason_counts": reason_counts,
    }


def should_run_feedback_backtest() -> bool:
    s = pending_feedback_summary()
    if s["pending_count"] >= 3:
        return True
    if s["recent_count"] >= 6 and s["recent_win_rate"] < 45:
        return True
    if s["recent_losses"] >= 3:
        return True
    return False


def mark_feedback_reviewed() -> None:
    rows = load_feedback(100000)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_STATE_FILE.write_text(
        json.dumps(
            {"reviewed_count": len(rows), "last_reviewed_at": utc_now_iso()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def reset_feedback() -> None:
    for path in (FEEDBACK_FILE, FEEDBACK_STATE_FILE):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
