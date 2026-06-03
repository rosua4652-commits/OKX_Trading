"""Backtest job runner — manual, background loop, history."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from app.backtest.engine import build_result
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
    if not config.backtest_auto_settings:
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


def get_history(limit: int = 30) -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))


def _save_result(result: BacktestResult) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    summary = {
        "id": result.id,
        "finished_at": result.finished_at or result.started_at,
        "status": result.status,
        "strategy_mode": result.strategy_mode,
        "symbols": result.symbols,
        "metrics": result.metrics.model_dump() if result.metrics else {},
        "recommendation": (
            result.recommendation.model_dump() if result.recommendation else None
        ),
        "trade_count": len(result.trades),
        "error": result.error,
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def _strategy_bar(config: AppConfig) -> str:
    modes = active_strategies(config)
    if StrategyMode.SWING in modes and StrategyMode.SCALP not in modes:
        return "swing"
    return "scalp"


async def _fetch_candles(config: AppConfig, symbols: list[str], limit: int) -> dict[str, list]:
    bar_key = _strategy_bar(config)
    out: dict[str, list] = {}
    for inst_id in symbols:
        _status.message = f"캔들 로드 {inst_id}"
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
        _status.message = "캔들 데이터 수집"

        if not symbols:
            symbols = await top_symbols(config.instrument_type, limit=8)
        if not symbols and config.scan_symbols:
            symbols = config.scan_symbols[:8]

        symbol_candles = await _fetch_candles(config, symbols, candle_limit)
        if not symbol_candles:
            raise RuntimeError("캔들 데이터 없음 (API/네트워크 확인)")

        _status.progress_pct = 35.0
        _status.phase = "simulate"
        _status.message = "시뮬레이션 실행"

        result = await asyncio.to_thread(
            build_result,
            config,
            list(symbol_candles.keys()),
            symbol_candles,
            logs,
            optimize,
        )

        _latest = result
        _save_result(result)
        live_cfg = _config_supplier() if _config_supplier else config
        _try_auto_apply_settings(live_cfg, result)
        _status.result_id = result.id
        _status.progress_pct = 100.0
        _status.phase = "done"
        rec = result.recommendation.min_score if result.recommendation else config.min_score
        _status.message = f"완료 — 추천 min_score {rec}"
        logger.info("Backtest %s done PnL=%s", result.id, result.metrics.total_pnl)
    except Exception as e:
        logger.exception("Backtest failed")
        logs.append(BacktestLogEntry(ts=utc_now_iso(), level="error", message=str(e)))
        fail = BacktestResult(
            id="error",
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
    candle_limit: int = 200,
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
    return True, "백테스트 시작됨"


async def _background_loop() -> None:
    """Run backtest on interval while server is up; results accumulate in history."""
    delay = max(30, settings.backtest_start_delay_sec)
    interval = max(300, settings.backtest_interval_sec)
    await asyncio.sleep(delay)

    while True:
        try:
            if _config_supplier is None:
                await asyncio.sleep(interval)
                continue
            if _status.running:
                await asyncio.sleep(60)
                continue
            cfg = _config_supplier()
            if not settings.backtest_auto_run:
                await asyncio.sleep(interval)
                continue
            _status.phase = "scheduled"
            _status.message = "자동 백테스트 예약 실행"
            await _run_job(cfg, [], settings.backtest_candle_limit, settings.backtest_optimize)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Background backtest error: %s", e)
        await asyncio.sleep(interval)


def start_background_loop(config_supplier: Callable[[], AppConfig]) -> None:
    global _background_task, _config_supplier
    _config_supplier = config_supplier
    if _background_task and not _background_task.done():
        return
    _background_task = asyncio.create_task(_background_loop())
    logger.info(
        "Backtest background loop started (delay=%ss interval=%ss)",
        settings.backtest_start_delay_sec,
        settings.backtest_interval_sec,
    )


def stop_background_loop() -> None:
    global _background_task
    if _background_task and not _background_task.done():
        _background_task.cancel()
    _background_task = None


def apply_recommendation(config: AppConfig) -> tuple[bool, str, dict[str, Any]]:
    latest = get_latest()
    if not latest or not latest.recommendation:
        return False, "적용할 추천 없음 (백테스트 먼저 실행)", {}
    rec = latest.recommendation
    changes = {
        "min_score": rec.min_score,
        "backtest_applied_at": utc_now_iso(),
        "backtest_result_id": latest.id,
    }
    return True, f"min_score → {rec.min_score} 적용", changes
