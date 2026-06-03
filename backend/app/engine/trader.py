"""Core trading engine — scan, analyze, enter, exit."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Callable, Optional

from app.config import settings
from app.engine.activity_log import push_activity
from app.engine.exit_rules import apply_strategy_defaults, should_exit
from app.engine.portfolio import PortfolioManager
from app.engine.portfolio_store import store
from app.engine.risk_manager import check_entry_allowed
from app.market.data_provider import market
from app.market.entry_analyzer import analyze_batch
from app.market.live_exchange import live_close, live_open
from app.market.scanner import scan_market, top_symbols
from app.models import (
    AppConfig,
    BotState,
    CoinCandidate,
    ManualOrderRequest,
    PortfolioSnapshot,
    PositionSide,
    StrategyMode,
    TradeMode,
    utc_now_iso,
)

logger = logging.getLogger("oat.trader")


class TradingEngine:
    def __init__(self) -> None:
        self.config = AppConfig()
        apply_strategy_defaults(self.config)
        self.portfolio: PortfolioManager = store.paper
        self.bot = BotState()
        self.candidates: list[CoinCandidate] = []
        self._task: Optional[asyncio.Task] = None
        self._listeners: list[Callable[[], None]] = []
        self._link_message = ""

    def bind_portfolio(self) -> None:
        self.portfolio = store.get(self.config.trade_mode)

    def _is_live(self) -> bool:
        return self.config.trade_mode == TradeMode.LIVE

    def _has_keys(self) -> bool:
        return bool(
            self.config.okx_api_key
            and self.config.okx_api_secret
            and self.config.okx_passphrase
        )

    def _log(self, phase: str, msg: str, level: str = "info") -> None:
        push_activity(self.bot, phase, msg, level)
        logger.info("[%s] %s", phase, msg)

    def _notify(self) -> None:
        for fn in self._listeners:
            try:
                fn()
            except Exception:
                pass

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    async def prices_map(self) -> dict[str, float]:
        return await market.price_map(self.config.instrument_type)

    async def get_status(self) -> dict:
        self.bind_portfolio()
        prices = await self.prices_map()
        self.portfolio.update_prices(prices)
        snap = self.portfolio.snapshot()
        linked = False
        if self._is_live() and self._has_keys():
            linked = True
        return {
            "config": self.config.model_dump(),
            "bot": self.bot.model_dump(),
            "portfolio": snap.model_dump(),
            "candidates": [c.model_dump() for c in self.candidates[:20]],
            "linked": linked,
            "link_message": self._link_message,
        }

    def update_config(self, config: AppConfig) -> None:
        self.config = apply_strategy_defaults(config)
        self._notify()

    async def start_bot(self, auto_invest: bool | None = None, strategy: StrategyMode | None = None) -> None:
        if auto_invest is not None:
            self.config.auto_invest = auto_invest
        if strategy is not None:
            self.config.strategy_mode = strategy
            apply_strategy_defaults(self.config)
        if self.bot.status.running:
            return
        self.bot.status.running = True
        self.bot.status.message = "봇 시작"
        self._log("start", f"자동매매 시작 ({self.config.strategy_mode.value}, {self.config.instrument_type.value})")
        self._task = asyncio.create_task(self._run_loop())
        self._notify()

    async def stop_bot(self) -> None:
        self.bot.status.running = False
        self.bot.status.message = "봇 중지"
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._log("stop", "자동매매 중지")
        self._notify()

    async def _run_loop(self) -> None:
        while self.bot.status.running:
            try:
                await self._tick()
            except Exception as e:
                self._log("error", f"틱 오류: {e}", "warn")
            await asyncio.sleep(settings.scan_interval_sec)

    async def _tick(self) -> None:
        self.bind_portfolio()
        self.bot.status.scan_count += 1
        self.bot.status.last_scan = utc_now_iso()
        self._log("scan", f"시장 스캔 #{self.bot.status.scan_count}")

        await self._check_exits()

        symbols = self.config.scan_symbols
        if not symbols:
            symbols = await top_symbols(self.config.instrument_type, limit=15)

        scanned = await scan_market(
            self.config.instrument_type,
            self.config.strategy_mode,
            limit=20,
        )
        analyzed = await analyze_batch(
            [c.inst_id for c in scanned[:15]],
            self.config.strategy_mode,
        )
        self.candidates = analyzed
        self._log("scan", f"후보 {len(analyzed)}개 분석 완료")

        if self.config.auto_invest:
            await self._auto_enter(analyzed)

        self._notify()

    async def _check_exits(self) -> None:
        prices = await self.prices_map()
        self.portfolio.update_prices(prices)

        for inst_id in list(self.portfolio.positions.keys()):
            pos = self.portfolio.positions.get(inst_id)
            if not pos:
                continue
            exit_flag, reason = should_exit(pos, self.config)
            if exit_flag:
                await self._close_position(inst_id, reason)

    async def _auto_enter(self, candidates: list[CoinCandidate]) -> None:
        snap = self.portfolio.snapshot()
        for cand in candidates:
            ok, msg = check_entry_allowed(self.config, snap, cand)
            if not ok:
                continue

            side = PositionSide.LONG
            if cand.outlook == "short" and self.config.allow_short:
                side = PositionSide.SHORT
            elif cand.outlook != "long":
                continue

            reason = f"AI {self.config.strategy_mode.value} | score={cand.score} | {', '.join(cand.reasons[:3])}"
            success = await self._open_position(cand.inst_id, side, cand.last_price, reason, cand.score)
            if success:
                snap = self.portfolio.snapshot()
                if len(snap.positions) >= self.config.max_positions:
                    break

    async def _open_position(
        self,
        inst_id: str,
        side: PositionSide,
        price: float,
        reason: str,
        score: float = 0.0,
    ) -> bool:
        size_usdt = self.config.order_size_usdt
        if price <= 0:
            return False

        if self._is_live() and self._has_keys():
            ok, msg, fill_price = await live_open(self.config, inst_id, side, size_usdt)
            if not ok:
                self._log("order", f"실거래 진입 실패: {msg}", "warn")
                return False
            price = fill_price
            self._log("order", f"실거래 진입: {inst_id} {side.value} @ {price}", "ok")

        quantity = size_usdt / price
        if self.config.instrument_type.value != "spot":
            quantity = max(1, math.floor(size_usdt / (price * 0.01)))

        pos = self.portfolio.open_position(
            inst_id, side, quantity, price, self.config, reason, score
        )
        if pos:
            self._log("entry", f"진입 {inst_id} {side.value} qty={quantity:.4f} @ {price:.2f}", "ok")
            return True
        self._log("entry", f"진입 실패 (잔고 부족): {inst_id}", "warn")
        return False

    async def _close_position(self, inst_id: str, reason: str) -> bool:
        pos = self.portfolio.positions.get(inst_id)
        if not pos:
            return False
        price = pos.current_price

        if self._is_live() and self._has_keys():
            ok, msg = await live_close(self.config, inst_id, pos.side, pos.quantity)
            if not ok:
                self._log("order", f"실거래 청산 실패: {msg}", "warn")
                return False
            self._log("order", f"실거래 청산: {inst_id} — {reason}", "ok")

        trade = self.portfolio.close_position(inst_id, price, reason)
        if trade:
            self._log(
                "exit",
                f"청산 {inst_id} PnL={trade.pnl:+.2f} ({trade.pnl_pct:+.1f}%) — {reason}",
                "ok" if trade.pnl >= 0 else "warn",
            )
            return True
        return False

    async def manual_order(self, req: ManualOrderRequest) -> tuple[bool, str]:
        side = req.side
        ticker = await market.ticker(req.inst_id)
        if not ticker:
            return False, "시세 없음"
        price = float(ticker.get("last", 0))
        old_size = self.config.order_size_usdt
        old_lev = self.config.leverage
        self.config.order_size_usdt = req.size_usdt
        self.config.leverage = req.leverage
        ok = await self._open_position(req.inst_id, side, price, "수동 주문")
        self.config.order_size_usdt = old_size
        self.config.leverage = old_lev
        self._notify()
        return (True, "주문 완료") if ok else (False, "주문 실패")

    async def manual_close(self, inst_id: str) -> tuple[bool, str]:
        ok = await self._close_position(inst_id, "수동 청산")
        self._notify()
        return (True, "청산 완료") if ok else (False, "청산 실패")

    async def close_all(self) -> int:
        count = 0
        for inst_id in list(self.portfolio.positions.keys()):
            if await self._close_position(inst_id, "전량 청산"):
                count += 1
        self._notify()
        return count

    async def scan_now(self) -> list[CoinCandidate]:
        scanned = await scan_market(
            self.config.instrument_type,
            self.config.strategy_mode,
            limit=20,
        )
        self.candidates = await analyze_batch(
            [c.inst_id for c in scanned[:15]],
            self.config.strategy_mode,
        )
        self._notify()
        return self.candidates
