"""FastAPI server ??OKX Auto Trader."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings as app_settings
from app.engine.trader import TradingEngine
from app.market.live_exchange import test_connection
from app.models import (
    OAT_BUILD,
    AppConfig,
    BotStartRequest,
    ConfigUpdateRequest,
    ManualOrderRequest,
    StatusResponse,
    PositionSideMode,
    StrategyMode,
    TradeMode,
)
from app.backtest.auto_apply import (
    auto_apply_decision,
    build_config_from_backtest,
    config_changed,
    get_auto_apply_history,
    record_auto_apply_decision,
)
from app.backtest.models import BacktestResult
from app.backtest.runner import (
    apply_recommendation,
    get_history,
    get_latest,
    get_status as backtest_status,
    interval_seconds,
    load_persisted_state,
    set_auto_apply_handler,
    start_backtest,
    start_background_loop,
    stop_background_loop,
)
from app.backtest.symbol_sl_tp import profiles_for_client
from app.backtest.live_feedback import pending_feedback_summary
from app.config_public import config_for_client, merge_config_update
from app.engine.portfolio_store import store
from app.storage.user_settings import load_settings, save_settings

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

engine = TradingEngine()
_ws_clients: set[WebSocket] = set()
_broadcast_task: asyncio.Task | None = None

api = APIRouter(prefix="/api")

saved = load_settings()
if saved:
    engine.update_config(saved)
else:
    engine.config.okx_api_key = app_settings.okx_api_key
    engine.config.okx_api_secret = app_settings.okx_api_secret
    engine.config.okx_passphrase = app_settings.okx_passphrase
    engine.config.okx_flag = app_settings.okx_flag
if engine.config.paper_initial_balance <= 0:
    engine.config.paper_initial_balance = app_settings.initial_balance


async def _broadcast_loop() -> None:
    while True:
        if _ws_clients:
            try:
                data = await engine.get_status()
                data["build"] = OAT_BUILD
                dead: set[WebSocket] = set()
                for ws in _ws_clients:
                    try:
                        await ws.send_json(data)
                    except Exception:
                        dead.add(ws)
                _ws_clients.difference_update(dead)
            except Exception:
                pass
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcast_task
    engine.bind_portfolio()
    load_persisted_state()
    _broadcast_task = asyncio.create_task(_broadcast_loop())

    def _on_backtest_complete(result: BacktestResult) -> None:
        before = engine.config
        updated = build_config_from_backtest(before, result)
        decision = auto_apply_decision(before, updated, result)
        record_auto_apply_decision(decision)
        if updated is None:
            engine._log("backtest", f"?먮룞 ?ㅼ젙 諛섏쁺 蹂대쪟: {decision['reason']}", "warn")
            return
        if not config_changed(before, updated):
            engine._log("backtest", "?먮룞 ?ㅼ젙 諛섏쁺 蹂대쪟: 蹂寃??놁쓬")
            return
        engine.apply_config(updated, "諛깊뀒?ㅽ듃 ?먮룞 ?곸슜")
        save_settings(engine.config)
        engine._log(
            "backtest",
            (
                f"?먮룞 ?ㅼ젙 諛섏쁺 ?꾨즺: score {before.min_score:g}->{updated.min_score:g}, "
                f"SL {before.stop_loss_pct:g}->{updated.stop_loss_pct:g}, "
                f"TP {before.take_profit_pct:g}->{updated.take_profit_pct:g}"
            ),
            "ok",
        )

    set_auto_apply_handler(_on_backtest_complete)
    start_background_loop(lambda: engine.config)
    yield
    stop_background_loop()
    if _broadcast_task:
        _broadcast_task.cancel()
        try:
            await _broadcast_task
        except asyncio.CancelledError:
            pass
    await engine.stop_bot()


app = FastAPI(title="OKX Auto Trader", version=OAT_BUILD, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/version")
async def version():
    return {"build": OAT_BUILD}


@api.get("/status")
async def status():
    data = await engine.get_status()
    data["build"] = OAT_BUILD
    from app.order_sizing import resolve_order_size_detail, resolve_order_size_usdt

    ps = engine.portfolio.snapshot()
    size_detail = resolve_order_size_detail(
        engine.config,
        ps,
        open_positions=len(ps.positions),
    )
    data["next_order_size_usdt"] = size_detail.notional_usdt
    data["next_order_size_detail"] = {
        "notional_usdt": size_detail.notional_usdt,
        "margin_usdt": size_detail.margin_usdt,
        "leverage": size_detail.leverage,
        "summary": size_detail.summary,
        "steps": size_detail.steps,
        "slots_remaining": size_detail.slots_remaining,
        "order_size_basis": size_detail.order_size_basis,
    }
    bt = backtest_status()
    latest = get_latest()
    data["backtest"] = {
        "status": bt.model_dump(),
        "result": latest.model_dump() if latest else None,
        "history": get_history(50),
        "symbol_profiles": profiles_for_client(),
        "auto_run": app_settings.backtest_auto_run,
        "interval_sec": interval_seconds(engine.config),
        "interval_minutes": engine.config.backtest_interval_minutes,
        "live_feedback": pending_feedback_summary(),
        "auto_apply_history": get_auto_apply_history(10),
    }
    return data


@api.post("/config")
async def update_config(req: ConfigUpdateRequest):
    merged = merge_config_update(req.config, engine.config)
    engine.update_config(merged)
    save_settings(engine.config)
    if engine.config.trade_mode == TradeMode.LIVE:
        engine._schedule_live_sync(include_fills=False)
    return {
        "ok": True,
        "config": config_for_client(engine.config),
        "message": "?ㅼ젙????λ릺?덉뒿?덈떎",
        "api_keys_configured": bool(
            engine.config.okx_api_key
            and engine.config.okx_api_secret
            and engine.config.okx_passphrase
        ),
    }


@api.get("/config")
async def get_config():
    return config_for_client(engine.config)


@api.post("/bot/start")
async def bot_start(req: BotStartRequest = BotStartRequest()):
    cfg = engine.config.model_copy(deep=True)
    if req.auto_invest is not None:
        cfg.auto_invest = req.auto_invest
    if req.strategy_mode is not None:
        cfg.strategy_mode = req.strategy_mode
    if req.position_side is not None:
        cfg.position_side = req.position_side
    engine.apply_config(cfg, "遊??쒖옉")
    await engine.start_bot(req.auto_invest, req.strategy_mode, req.position_side)
    save_settings(engine.config)
    return {"ok": True, "running": engine.bot.status.running}


@api.post("/bot/stop")
async def bot_stop():
    await engine.stop_bot()
    return {"ok": True, "running": False}


@api.post("/scan")
async def scan_now():
    candidates = await engine.scan_now()
    return {"candidates": [c.model_dump() for c in candidates]}


@api.get("/symbols/search")
async def search_symbols(q: str = Query("", max_length=40), limit: int = 20):
    from app.market.data_provider import market
    from app.market.okx_client import get_okx_client
    from app.models import InstrumentType

    query = q.strip().upper().replace("/", "-")
    if query and not query.endswith("USDT") and "-USDT" not in query:
        query = f"{query}-USDT"
    rows = await market.tickers(InstrumentType.SWAP)
    meta_rows = await asyncio.to_thread(get_okx_client().get_instruments, "SWAP")
    meta_by_id = {str(m.get("instId") or ""): m for m in meta_rows}

    def leverage_options(inst_id: str) -> list[int]:
        meta = meta_by_id.get(inst_id) or {}
        raw = meta.get("lever") or meta.get("maxLever") or meta.get("maxLeverage") or 125
        try:
            max_lev = int(float(raw))
        except (TypeError, ValueError):
            max_lev = 125
        base = [1, 2, 3, 5, 10, 20, 30, 50, 75, 100, 125]
        opts = [x for x in base if x <= max_lev]
        return opts or [1]

    out: list[dict] = []
    for t in rows:
        inst_id = str(t.get("instId") or "")
        if not inst_id.endswith("-SWAP"):
            continue
        if query and query not in inst_id.upper():
            continue
        try:
            last = float(t.get("last") or 0)
            open24 = float(t.get("open24h") or last or 0)
            vol_ccy = float(t.get("volCcy24h") or 0)
            vol = vol_ccy if vol_ccy > 0 else float(t.get("vol24h") or 0) * last
            change = (last - open24) / open24 * 100 if open24 > 0 else 0.0
        except (TypeError, ValueError):
            last, vol, change = 0.0, 0.0, 0.0
        out.append({
            "inst_id": inst_id,
            "last": last,
            "change_24h_pct": round(change, 2),
            "volume_24h_usdt": round(vol, 0),
            "leverage_options": leverage_options(inst_id),
        })
    out.sort(key=lambda x: x["volume_24h_usdt"], reverse=True)
    return {"symbols": out[: max(1, min(50, limit))]}


class CloseRequest(BaseModel):
    inst_id: str


@api.post("/order/manual")
async def manual_order(req: ManualOrderRequest):
    ok, msg = await engine.manual_order(req)
    return {"ok": ok, "message": msg}


@api.post("/order/close")
async def close_position(req: CloseRequest):
    ok, msg = await engine.manual_close(req.inst_id)
    return {"ok": ok, "message": msg}


class PositionSlTpRequest(BaseModel):
    inst_id: str
    sl_pct: float
    tp_pct: float


class PositionAutoSlTpRequest(BaseModel):
    inst_id: str
    disabled: bool | None = None
    sl_disabled: bool | None = None
    tp_disabled: bool | None = None
    profit_protect_disabled: bool | None = None


@api.post("/position/sl-tp")
async def set_position_sl_tp(req: PositionSlTpRequest):
    ok, msg = await engine.set_position_sl_tp(req.inst_id, req.sl_pct, req.tp_pct)
    return {"ok": ok, "message": msg}


@api.post("/position/sl-tp/disabled")
async def set_position_auto_sl_tp_disabled(req: PositionAutoSlTpRequest):
    ok, msg = await engine.set_position_auto_sl_tp_disabled(
        req.inst_id,
        req.disabled,
        req.sl_disabled,
        req.tp_disabled,
        req.profit_protect_disabled,
    )
    return {"ok": ok, "message": msg}


@api.post("/position/sl-tp/auto")
async def reset_position_sl_tp(req: CloseRequest):
    ok, msg = await engine.reset_position_sl_tp_auto(req.inst_id)
    return {"ok": ok, "message": msg}


@api.post("/order/close-all")
async def close_all():
    count = await engine.close_all()
    return {"ok": True, "closed": count}


class PaperResetRequest(BaseModel):
    initial_balance: float | None = None


@api.post("/paper/reset")
async def reset_paper(req: PaperResetRequest = PaperResetRequest()):
    bal = req.initial_balance if req.initial_balance is not None else engine.config.paper_initial_balance
    if bal is None or bal <= 0:
        return {"ok": False, "message": "초기 자금은 0보다 커야 합니다."}
    try:
        bal = await engine.reset_paper_portfolio(bal)
        save_settings(engine.config)
        snap = store.paper.snapshot()
        return {
            "ok": True,
            "message": f"紐⑥쓽?ъ옄 珥덇린???꾨즺 (?붽퀬 ${bal:,.0f})",
            "balance": bal,
            "equity": snap.equity,
        }
    except Exception as e:
        return {"ok": False, "message": f"珥덇린???ㅽ뙣: {e}"}


@api.post("/portfolio/stats/reset")
async def reset_portfolio_stats():
    try:
        ok, msg = await engine.reset_trade_stats()
        return {"ok": ok, "message": msg}
    except Exception as e:
        return {"ok": False, "message": f"?듦퀎 珥덇린???ㅽ뙣: {e}"}


@api.post("/test-connection")
async def test_conn():
    ok, msg = await test_connection(engine.config)
    if ok and "|AUTO_FLAG:" in msg:
        parts = msg.split("|AUTO_FLAG:")
        flag = parts[1].split("|")[0].strip()
        cfg = engine.config.model_copy(deep=True)
        cfg.okx_flag = flag
        engine.apply_config(cfg, "연결 테스트")
        save_settings(engine.config)
        msg = parts[0] + (f" 자동 설정: {'모의' if flag == '1' else '실거래'} 저장됨" if len(parts) > 1 else "")
    engine._link_message = msg
    return {"ok": ok, "message": msg, "okx_flag": engine.config.okx_flag}


class TradeModeRequest(BaseModel):
    mode: TradeMode


@api.post("/trade-mode")
async def set_trade_mode(req: TradeModeRequest):
    cfg = engine.config.model_copy(deep=True)
    cfg.trade_mode = req.mode
    cfg.okx_flag = "1" if req.mode == TradeMode.PAPER else "0"
    engine.apply_config(cfg, "嫄곕옒 紐⑤뱶")
    engine.bind_portfolio()
    if req.mode == TradeMode.LIVE:
        await engine._sync_live_if_needed(include_fills=False)
    save_settings(engine.config)
    return {"ok": True, "mode": req.mode.value, "okx_flag": engine.config.okx_flag}


class StrategyRequest(BaseModel):
    strategy: StrategyMode


@api.post("/strategy")
async def set_strategy(req: StrategyRequest):
    cfg = engine.config.model_copy(deep=True)
    cfg.strategy_mode = req.strategy
    engine.apply_config(cfg, "전략 변경")
    save_settings(engine.config)
    return {"ok": True, "strategy": req.strategy.value}


class PositionSideRequest(BaseModel):
    mode: PositionSideMode


@api.post("/position-side")
async def set_position_side(req: PositionSideRequest):
    cfg = engine.config.model_copy(deep=True)
    cfg.position_side = req.mode
    if req.mode == PositionSideMode.SHORT:
        cfg.allow_short = True
    engine.apply_config(cfg, "吏꾩엯 諛⑺뼢")
    save_settings(engine.config)
    return {"ok": True, "position_side": req.mode.value}


@api.get("/candles")
async def get_candles(inst_id: str, strategy: str = "scalp", side: str = "long"):
    from app.market.candles_api import fetch_chart_candles
    from app.market.dynamic_sl_tp import compute_dynamic_sl_tp
    from app.models import PositionSide

    try:
        strat = StrategyMode(strategy)
    except ValueError:
        strat = StrategyMode.SCALP
    if strat == StrategyMode.BOTH:
        strat = StrategyMode.SCALP
    candles = await fetch_chart_candles(inst_id, strategy, 120)
    entry = float(candles[-1]["close"]) if candles else 0.0
    pos_side = PositionSide.SHORT if side == "short" else PositionSide.LONG
    if entry > 0:
        plan = await compute_dynamic_sl_tp(inst_id, entry, pos_side, strat, engine.config)
        sl_pct, tp_pct = plan.sl_pct, plan.tp_pct
        sl_tp_method = plan.method
    else:
        from app.strategy_utils import sl_tp_pcts
        sl_pct, tp_pct = sl_tp_pcts(engine.config, strat)
        sl_tp_method = "湲곕낯"
    return {
        "inst_id": inst_id,
        "strategy": strategy,
        "candles": candles,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "sl_tp_method": sl_tp_method,
    }


@api.get("/trades")
async def get_trades():
    engine.bind_portfolio()
    if engine.config.trade_mode == TradeMode.LIVE:
        await engine._sync_live_if_needed(force=True, include_fills=True)
    return {"trades": [t.model_dump() for t in engine.portfolio.trades[-50:]]}


class BacktestRunRequest(BaseModel):
    symbols: list[str] = []
    candle_limit: int = 500
    months: int = 3
    optimize: bool = True


@api.post("/backtest/run")
async def backtest_run(req: BacktestRunRequest = BacktestRunRequest()):
    months = max(3, min(6, int(req.months or 3)))
    candle_limit = max(80, min(60000, int(req.candle_limit or 500)))
    if engine.config.backtest_candle_limit != candle_limit or engine.config.backtest_period_months != months:
        cfg = engine.config.model_copy(deep=True)
        cfg.backtest_candle_limit = candle_limit
        cfg.backtest_period_months = months
        engine.apply_config(cfg, "백테스트 기간/캔들")
        save_settings(engine.config)
    ok, msg = await start_backtest(
        engine.config,
        req.symbols or None,
        candle_limit,
        req.optimize,
    )
    return {"ok": ok, "message": msg}


@api.get("/backtest/status")
async def backtest_get_status():
    st = backtest_status()
    latest = get_latest()
    return {
        "status": st.model_dump(),
        "result": latest.model_dump() if latest else None,
    }


@api.get("/backtest/latest")
async def backtest_latest():
    latest = get_latest()
    if not latest:
        return {"ok": False, "message": "寃곌낵 ?놁쓬"}
    return {"ok": True, "result": latest.model_dump()}


@api.get("/backtest/history")
async def backtest_history(limit: int = 30):
    return {"history": get_history(limit)}


@api.post("/backtest/apply")
async def backtest_apply():
    latest = get_latest()
    if not latest:
        return {"ok": False, "message": "?곸슜??諛깊뀒?ㅽ듃 寃곌낵 ?놁쓬"}
    updated = build_config_from_backtest(engine.config, latest)
    if updated is None:
        if not latest.recommendation:
            return {"ok": False, "message": "異붿쿇 ?놁쓬"}
        updated = engine.config.model_copy(deep=True)
        rec = latest.recommendation
        updated.min_score = float(rec.min_score)
        if rec.stop_loss_pct > 0:
            updated.stop_loss_pct = float(rec.stop_loss_pct)
        if rec.take_profit_pct > 0:
            updated.take_profit_pct = float(rec.take_profit_pct)
    engine.apply_config(updated, "諛깊뀒?ㅽ듃 異붿쿇 ?곸슜")
    save_settings(engine.config)
    rec = latest.recommendation
    msg_parts = [f"min_score={engine.config.min_score}"]
    if rec and rec.stop_loss_pct > 0:
        msg_parts.append(f"SL {engine.config.stop_loss_pct}%")
    if rec and rec.take_profit_pct > 0:
        msg_parts.append(f"TP {engine.config.take_profit_pct}%")
    msg_parts.append(f"二쇰Ц={engine.config.position_size_mode}")
    return {
        "ok": True,
        "message": ", ".join(msg_parts),
        "min_score": engine.config.min_score,
        "stop_loss_pct": engine.config.stop_loss_pct,
        "take_profit_pct": engine.config.take_profit_pct,
        "config": config_for_client(engine.config),
    }


app.include_router(api)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = STATIC_DIR / "index.html"
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(index)
