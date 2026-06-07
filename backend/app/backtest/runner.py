"""Backtest job runner ??manual, background loop, history."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from app.backtest.engine import build_result
from app.backtest.history_sl_tp import exit_stats_from_trades, merge_sl_tp_with_history
from app.backtest.live_feedback import (
    mark_feedback_reviewed,
    pending_feedback_summary,
    should_run_feedback_backtest,
)
from app.backtest.models import BacktestLogEntry, BacktestResult, BacktestStatus
from app.config import settings
from app.market.data_provider import market
from app.market.scanner import top_symbols
from app.models import AppConfig, StrategyMode, utc_now_iso
from app.strategy_utils import active_strategies

logger = logging.getLogger("oat.backtest")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
RESULT_FILE = DATA_DIR / "backtest_latest.json"
HISTORY_FILE = DATA_DIR / "backtest_history.jsonl"

_status = BacktestStatus()
_latest: Optional[BacktestResult] = None
_task: Optional[asyncio.Task] = None
_background_task: Optional[asyncio.Task] = None
_config_supplier: Optional[Callable[[], AppConfig]] = None
_auto_apply_handler: Optional[Callable[[BacktestResult], None]] = None


def set_auto_apply_handler(handler: Callable[[BacktestResult], None] | None) -> None:
    global _auto_apply_handler
    _auto_apply_handler = handler


def _try_auto_apply_settings(config: AppConfig, result: BacktestResult) -> None:
    if not config.backtest_auto_settings and not config.backtest_auto_sl_tp:
        return
    if result.status != "done" or not result.recommendation:
        return
    if _auto_apply_handler:
        try:
            _auto_apply_handler(result)
        except Exception as e:
            logger.warning("Auto-apply backtest settings failed: %s", e)


def get_status() -> BacktestStatus:
    return _status.model_copy(deep=True)


def get_latest() -> Optional[BacktestResult]:
    if _latest:
        return _latest.model_copy(deep=True)
    if RESULT_FILE.exists():
        try:
            data = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
            return BacktestResult(**data)
        except Exception:
            return None
    return None


def load_persisted_state() -> None:
    """Restore the latest result pointer after a server restart."""
    global _latest, _status
    latest = get_latest()
    if not latest:
        return
    _latest = latest
    _status.result_id = latest.id
    _status.phase = latest.status if latest.status in ("done", "error") else "idle"
    if latest.status == "done" and latest.metrics:
        _status.progress_pct = 100.0
        _status.message = (
            f"理쒓렐 諛깊뀒?ㅽ듃 蹂듦뎄 ??PnL {latest.metrics.total_pnl:+.2f} "
            f"?밸쪧 {latest.metrics.win_rate}%"
        )
    elif latest.error:
        _status.message = latest.error


def get_history(limit: int = 30) -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-max(limit * 2, limit):]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out = list(reversed(out))
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for entry in out:
        key = (str(entry.get("id") or ""), str(entry.get("finished_at") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped[:limit]


def _merge_history_sl_tp(result: BacktestResult, config: AppConfig) -> BacktestResult:
    """Blend grid SL/TP with accumulated history when auto SL/TP is enabled."""
    if not result.recommendation:
        return result
    rec = result.recommendation
    if rec.stop_loss_pct <= 0 or rec.take_profit_pct <= 0:
        return result

    prior = get_history(50)
    merged_sl, merged_tp, note = merge_sl_tp_with_history(
        rec.stop_loss_pct,
        rec.take_profit_pct,
        prior,
        use_history=config.backtest_auto_sl_tp or len(prior) >= 3,
    )
    if merged_sl == rec.stop_loss_pct and merged_tp == rec.take_profit_pct:
        return result

    updated = result.model_copy(deep=True)
    updated.recommendation = rec.model_copy(deep=True)
    updated.recommendation.stop_loss_pct = merged_sl
    updated.recommendation.take_profit_pct = merged_tp
    updated.recommendation.sl_tp_reason = f"{rec.sl_tp_reason} | {note}"
    snap = dict(updated.params_snapshot or {})
    snap["stop_loss_pct_applied"] = merged_sl
    snap["take_profit_pct_applied"] = merged_tp
    updated.params_snapshot = snap
    return updated


def _save_result(result: BacktestResult) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    trade_dicts = [t.model_dump() for t in result.trades]
    exit_stats = exit_stats_from_trades(trade_dicts)
    applied_sl = result.params_snapshot.get("stop_loss_pct_applied") or result.params_snapshot.get(
        "stop_loss_pct"
    )
    applied_tp = result.params_snapshot.get("take_profit_pct_applied") or result.params_snapshot.get(
        "take_profit_pct"
    )
    summary = {
        "id": result.id,
        "finished_at": result.finished_at or result.started_at,
        "status": result.status,
        "strategy_mode": result.strategy_mode,
        "symbols": result.symbols,
        "direction": (
            result.recommendation.direction if result.recommendation else None
        ),
        "window_ratio": (
            result.recommendation.window_ratio if result.recommendation else None
        ),
        "metrics": result.metrics.model_dump() if result.metrics else {},
        "recommendation": (
            result.recommendation.model_dump() if result.recommendation else None
        ),
        "trade_count": len(result.trades),
        "exit_stats": exit_stats,
        "applied_sl_pct": applied_sl,
        "applied_tp_pct": applied_tp,
        "zone_walkforward": result.zone_walkforward.model_dump(),
        "error": result.error,
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def interval_seconds(config: AppConfig) -> int:
    """Saved UI setting: backtest_interval_minutes (1??440)."""
    mins = max(1, min(1440, int(config.backtest_interval_minutes or 60)))
    return mins * 60


def _strategy_bar(config: AppConfig) -> str:
    modes = active_strategies(config)
    if StrategyMode.SWING in modes and StrategyMode.SCALP not in modes:
        return "swing"
    return "scalp"


async def _fetch_candles(
    config: AppConfig,
    symbols: list[str],
    limit: int,
    months: int | None = None,
) -> dict[str, list]:
    bar_key = _strategy_bar(config)
    months = max(3, min(6, int(months or config.backtest_period_months or 3)))
    out: dict[str, list] = {}
    for inst_id in symbols:
        _status.message = f"캔들 로드 {inst_id} ({months}개월)"
        candles = await market.candles_months(inst_id, bar_key, months=months)
        if not candles:
            candles = await market.candles(inst_id, bar_key, limit=limit)
        if candles:
            out[inst_id] = candles
    return out


async def _run_job(config: AppConfig, symbols: list[str], candle_limit: int, optimize: bool) -> None:
    global _latest, _status
    logs: list[BacktestLogEntry] = []
    try:
        _status.running = True
        _status.progress_pct = 5.0
        _status.phase = "fetch"
        _status.message = "罹붾뱾 ?곗씠???섏쭛"

        if not symbols:
            symbols = await top_symbols(config.instrument_type, limit=8)
        if not symbols and config.scan_symbols:
            symbols = config.scan_symbols[:8]

        months = max(3, min(6, int(config.backtest_period_months or 3)))
        symbol_candles = await _fetch_candles(config, symbols, candle_limit, months)
        if not symbol_candles:
            raise RuntimeError("罹붾뱾 ?곗씠???놁쓬 (API/?ㅽ듃?뚰겕 ?뺤씤)")

        _status.progress_pct = 35.0
        _status.phase = "simulate"
        _status.message = "?쒕??덉씠???ㅽ뻾"

        result = await asyncio.to_thread(
            build_result,
            config,
            list(symbol_candles.keys()),
            symbol_candles,
            logs,
            optimize,
        )

        live_cfg = _config_supplier() if _config_supplier else config
        result = _merge_history_sl_tp(result, live_cfg)
        _latest = result
        _save_result(result)
        _try_auto_apply_settings(live_cfg, result)
        _status.result_id = result.id
        _status.progress_pct = 100.0
        _status.phase = "done"
        rec = result.recommendation
        if rec:
            _status.message = (
                f"?꾨즺 ??score {rec.min_score} SL {rec.stop_loss_pct}% TP {rec.take_profit_pct}% "
                f"?밸쪧 {result.metrics.win_rate}%"
            )
        else:
            _status.message = "?꾨즺"
        logger.info("Backtest %s done PnL=%s", result.id, result.metrics.total_pnl)
    except Exception as e:
        logger.exception("Backtest failed")
        logs.append(BacktestLogEntry(ts=utc_now_iso(), level="error", message=str(e)))
        fail = BacktestResult(
            id=f"err-{uuid.uuid4().hex[:8]}",
            status="error",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            strategy_mode=config.strategy_mode.value,
            symbols=symbols,
            logs=logs,
            error=str(e),
        )
        _latest = fail
        _save_result(fail)
        _status.phase = "error"
        _status.message = str(e)
    finally:
        _status.running = False


async def start_backtest(
    config: AppConfig,
    symbols: list[str] | None = None,
    candle_limit: int = 500,
    optimize: bool = True,
) -> tuple[bool, str]:
    global _task, _status
    if _status.running:
        return False, "백테스트 실행 중"

    sym_list = list(symbols or [])
    _status = BacktestStatus(
        running=True,
        progress_pct=0,
        phase="start",
        message="시작",
    )
    _task = asyncio.create_task(_run_job(config, sym_list, candle_limit, optimize))
    return True, "백테스트 시작"


async def _background_loop() -> None:
    """Server start -> run backtest in a loop until shutdown (no button needed)."""
    delay = max(0, min(30, settings.backtest_start_delay_sec))
    if delay > 0:
        await asyncio.sleep(delay)

    feedback_check_at = 0.0
    while True:
        interval = 3600
        try:
            if _config_supplier is None:
                await asyncio.sleep(10)
                continue
            if _status.running:
                await asyncio.sleep(15)
                continue
            cfg = _config_supplier()
            interval = interval_seconds(cfg)
            if not settings.backtest_auto_run:
                await asyncio.sleep(interval)
                continue
            now = asyncio.get_running_loop().time()
            if now >= feedback_check_at:
                feedback_check_at = now + 60
                if should_run_feedback_backtest():
                    summary = pending_feedback_summary()
                    symbols = summary["symbols"] or []
                    _status.phase = "feedback"
                    _status.message = (
                        f"실거래 피드백 재검증: 최근 승률 {summary['recent_win_rate']}%, "
                        f"손실 {summary['recent_losses']}건"
                    )
                    candle_limit = max(
                        300,
                        min(60000, int(cfg.backtest_candle_limit or settings.backtest_candle_limit)),
                    )
                    await _run_job(cfg, symbols, candle_limit, True)
                    mark_feedback_reviewed()
                    await asyncio.sleep(60)
                    continue
            _status.phase = "scheduled"
            _status.message = "자동 백테스트 실행"
            candle_limit = max(80, min(60000, int(cfg.backtest_candle_limit or settings.backtest_candle_limit)))
            await _run_job(cfg, [], candle_limit, settings.backtest_optimize)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Background backtest error: %s", e)
            if _config_supplier:
                try:
                    interval = interval_seconds(_config_supplier())
                except Exception:
                    interval = max(60, settings.backtest_interval_sec)
        await asyncio.sleep(interval)


def start_background_loop(config_supplier: Callable[[], AppConfig]) -> None:
    global _background_task, _config_supplier
    _config_supplier = config_supplier
    if _background_task and not _background_task.done():
        return
    _background_task = asyncio.create_task(_background_loop())
    logger.info(
        "Backtest background loop started (delay=%ss, interval from config minutes)",
        settings.backtest_start_delay_sec,
    )


def stop_background_loop() -> None:
    global _background_task
    if _background_task and not _background_task.done():
        _background_task.cancel()
    _background_task = None


def apply_recommendation(config: AppConfig) -> tuple[bool, str, dict[str, Any]]:
    latest = get_latest()
    if not latest or not latest.recommendation:
        return False, "?곸슜??異붿쿇 ?놁쓬 (諛깊뀒?ㅽ듃 癒쇱? ?ㅽ뻾)", {}
    rec = latest.recommendation
    changes: dict[str, Any] = {
        "min_score": rec.min_score,
        "backtest_applied_at": utc_now_iso(),
        "backtest_result_id": latest.id,
    }
    if rec.stop_loss_pct > 0:
        changes["stop_loss_pct"] = rec.stop_loss_pct
    if rec.take_profit_pct > 0:
        changes["take_profit_pct"] = rec.take_profit_pct
    msg = f"min_score ??{rec.min_score}"
    if rec.stop_loss_pct > 0 and rec.take_profit_pct > 0:
        msg += f", SL {rec.stop_loss_pct}% / TP {rec.take_profit_pct}%"
    return True, msg + " ?곸슜", changes
