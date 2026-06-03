"""FastAPI server — OKX Auto Trader."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
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
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcast_task
    engine.bind_portfolio()
    _broadcast_task = asyncio.create_task(_broadcast_loop())
    yield
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
    from app.order_sizing import resolve_order_size_usdt

    ps = engine.portfolio.snapshot()
    data["next_order_size_usdt"] = resolve_order_size_usdt(
        engine.config,
        ps,
        open_positions=len(ps.positions),
    )
    return data


@api.post("/config")
async def update_config(req: ConfigUpdateRequest):
    merged = merge_config_update(req.config, engine.config)
    engine.update_config(merged)
    save_settings(engine.config)
    if engine.config.trade_mode == TradeMode.LIVE:
        await engine._sync_live_if_needed()
    return {
        "ok": True,
        "message": "설정이 저장되었습니다",
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
    engine.apply_config(cfg, "봇 시작")
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


@api.post("/position/sl-tp")
async def set_position_sl_tp(req: PositionSlTpRequest):
    ok, msg = await engine.set_position_sl_tp(req.inst_id, req.sl_pct, req.tp_pct)
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
    try:
        bal = await engine.reset_paper_portfolio(bal)
        save_settings(engine.config)
        snap = store.paper.snapshot()
        return {
            "ok": True,
            "message": f"모의투자 초기화 완료 (잔고 ${bal:,.0f})",
            "balance": bal,
            "equity": snap.equity,
        }
    except Exception as e:
        return {"ok": False, "message": f"초기화 실패: {e}"}


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
        msg = parts[0] + (f" — 설정에 {('데모' if flag == '1' else '실거래')} 저장됨" if len(parts) > 1 else "")
    engine._link_message = msg
    return {"ok": ok, "message": msg, "okx_flag": engine.config.okx_flag}


class TradeModeRequest(BaseModel):
    mode: TradeMode


@api.post("/trade-mode")
async def set_trade_mode(req: TradeModeRequest):
    cfg = engine.config.model_copy(deep=True)
    cfg.trade_mode = req.mode
    cfg.okx_flag = "1" if req.mode == TradeMode.PAPER else "0"
    engine.apply_config(cfg, "거래 모드")
    engine.bind_portfolio()
    if req.mode == TradeMode.LIVE:
        await engine._sync_live_if_needed()
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
    engine.apply_config(cfg, "진입 방향")
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
        sl_tp_method = "기본"
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
    return {"trades": [t.model_dump() for t in engine.portfolio.trades[-50:]]}


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
