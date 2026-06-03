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
    StrategyMode,
    TradeMode,
)
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
    return data


@api.post("/config")
async def update_config(req: ConfigUpdateRequest):
    engine.update_config(req.config)
    save_settings(engine.config)
    return {"ok": True}


@api.get("/config")
async def get_config():
    return engine.config


@api.post("/bot/start")
async def bot_start(req: BotStartRequest = BotStartRequest()):
    await engine.start_bot(req.auto_invest, req.strategy_mode)
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


@api.post("/order/close-all")
async def close_all():
    count = await engine.close_all()
    return {"ok": True, "closed": count}


@api.post("/test-connection")
async def test_conn():
    ok, msg = await test_connection(engine.config)
    engine._link_message = msg
    return {"ok": ok, "message": msg}


class TradeModeRequest(BaseModel):
    mode: TradeMode


@api.post("/trade-mode")
async def set_trade_mode(req: TradeModeRequest):
    engine.config.trade_mode = req.mode
    engine.bind_portfolio()
    save_settings(engine.config)
    return {"ok": True, "mode": req.mode.value}


class StrategyRequest(BaseModel):
    strategy: StrategyMode


@api.post("/strategy")
async def set_strategy(req: StrategyRequest):
    engine.config.strategy_mode = req.strategy
    save_settings(engine.config)
    return {"ok": True, "strategy": req.strategy.value}


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
