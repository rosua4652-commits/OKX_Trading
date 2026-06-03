"""Core trading engine — scan, analyze, enter, exit."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from app.config import settings
from app.contract_sizing import swap_contract_count, swap_notional_usdt
from app.engine.activity_log import push_activity
from app.config_changelog import format_config_changes
from app.config_public import config_for_client
from app.engine.exit_rules import apply_strategy_defaults, should_exit
from app.order_sizing import entry_cost_usdt, resolve_order_size_usdt
from app.strategy_utils import active_strategies
from app.engine.portfolio import PortfolioManager
from app.engine.portfolio_store import store
from app.entry_signals import resolve_entry_side
from app.engine.risk_manager import check_entry_allowed
from app.market.data_provider import market
from app.market.entry_analyzer import analyze_batch
from app.market.dynamic_sl_tp import compute_dynamic_sl_tp
from app.market.live_account import sync_live_portfolio
from app.market.live_exchange import live_close, live_open
from app.market.instrument_rules import swap_sizing_rules
from app.market.scanner import scan_market, top_symbols
from app.models import (
    AppConfig,
    BotState,
    CoinCandidate,
    InstrumentType,
    ManualOrderRequest,
    PortfolioSnapshot,
    PositionSide,
    PositionSideMode,
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
        self._portfolio_sync_message = ""

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

    async def _refresh_dynamic_sl_tp_all(self) -> None:
        for inst_id, pos in list(self.portfolio.positions.items()):
            if pos.auto_sl_tp_disabled or pos.sl_tp_manual or pos.entry_price <= 0:
                continue
            strat = pos.strategy_mode
            if strat == StrategyMode.BOTH:
                strat = StrategyMode.SCALP
            try:
                plan = await compute_dynamic_sl_tp(
                    inst_id,
                    pos.entry_price,
                    pos.side,
                    strat,
                    self.config,
                )
                self.portfolio.apply_sl_tp_plan(inst_id, plan)
            except Exception as e:
                self._log("sync", f"SL/TP 갱신 실패 {inst_id}: {e}", "warn")

    async def _sync_live_if_needed(self) -> None:
        if not self._is_live():
            self._portfolio_sync_message = ""
            return
        if not self._has_keys():
            self._portfolio_sync_message = "실거래: API 키를 설정·저장하세요"
            return
        ok, msg = sync_live_portfolio(self.portfolio, self.config)
        self._portfolio_sync_message = msg
        if ok:
            logger.debug(msg)
        else:
            self._log("sync", msg, "warn")

    async def get_status(self) -> dict:
        self.bind_portfolio()
        if self._is_live():
            await self._sync_live_if_needed()
        await self._refresh_dynamic_sl_tp_all()
        prices = await self.prices_map()
        if not self._is_live():
            self.portfolio.update_prices(prices)
        elif self.portfolio.positions:
            self.portfolio.update_prices(prices)
        snap = self.portfolio.snapshot()
        linked = False
        if self._has_keys() and self._link_message and "실패" not in self._link_message and "오류" not in self._link_message:
            linked = "연결" in self._link_message or self._link_message.lower().startswith("ok")
        out: dict = {
            "config": config_for_client(self.config),
            "bot": self.bot.model_dump(),
            "portfolio": snap.model_dump(),
            "candidates": [c.model_dump() for c in self.candidates[:20]],
            "linked": linked,
            "link_message": self._link_message,
            "portfolio_source": "okx" if self._is_live() else "paper",
            "portfolio_sync_message": self._portfolio_sync_message,
            "trades": [t.model_dump() for t in self.portfolio.trades[-200:]],
        }
        try:
            from app.backtest.runner import (
                get_history,
                get_latest,
                get_status as bt_status,
                interval_seconds,
            )
            from app.backtest.symbol_sl_tp import profiles_for_client
            from app.config import settings as app_settings

            bt = bt_status()
            latest = get_latest()
            out["backtest"] = {
                "status": bt.model_dump(),
                "result": latest.model_dump() if latest else None,
                "history": get_history(20),
                "symbol_profiles": profiles_for_client(),
                "auto_run": app_settings.backtest_auto_run,
                "interval_sec": interval_seconds(self.config),
                "interval_minutes": self.config.backtest_interval_minutes,
            }
        except Exception:
            pass
        return out

    def apply_config(self, config: AppConfig, source: str = "설정") -> None:
        old = self.config.model_copy(deep=True)
        self.config = apply_strategy_defaults(config)
        changes = format_config_changes(old, self.config)
        if changes:
            self._log("config", f"[{source}] " + " | ".join(changes))
        self._notify()

    def update_config(self, config: AppConfig) -> None:
        self.apply_config(config, "설정 저장")

    async def start_bot(
        self,
        auto_invest: bool | None = None,
        strategy: StrategyMode | None = None,
        position_side: PositionSideMode | None = None,
    ) -> None:
        if auto_invest is not None:
            self.config.auto_invest = auto_invest
        if strategy is not None:
            self.config.strategy_mode = strategy
            apply_strategy_defaults(self.config)
        if position_side is not None:
            self.config.position_side = position_side
        if self.bot.status.running:
            return
        self.bot.status.running = True
        self.bot.status.message = "봇 시작"
        strat_label = self.config.strategy_mode.value
        if self.config.strategy_mode == StrategyMode.BOTH:
            strat_label = "단타+장타"
        self._log("start", f"자동매매 시작 ({strat_label}, {self.config.instrument_type.value})")
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
        if self._is_live():
            await self._sync_live_if_needed()
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
        n_long = sum(1 for c in analyzed if c.outlook == "long")
        n_short = sum(1 for c in analyzed if c.outlook == "short")
        side_mode = self.config.position_side.value
        self._log(
            "scan",
            f"후보 {len(analyzed)} (판단 롱 {n_long} / 숏 {n_short}) · 진입모드={side_mode}",
        )

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

    def _resolve_entry_side(self, cand: CoinCandidate) -> PositionSide | None:
        return resolve_entry_side(self.config, cand)

    async def _auto_enter(self, candidates: list[CoinCandidate]) -> None:
        snap = self.portfolio.snapshot()
        for cand in candidates:
            if any(p.inst_id == cand.inst_id for p in snap.positions):
                continue

            side = self._resolve_entry_side(cand)
            if side is None:
                continue

            entered = False
            for strat in active_strategies(self.config):
                ok, msg = check_entry_allowed(
                    self.config, snap, cand, strat, entry_side=side
                )
                if not ok:
                    continue

                label = "단타" if strat == StrategyMode.SCALP else "장타"
                dir_label = "숏" if side == PositionSide.SHORT else "롱"
                reason = (
                    f"AI {label} {dir_label} | score={cand.score} | "
                    f"{', '.join(cand.reasons[:3])}"
                )
                success = await self._open_position(
                    cand.inst_id,
                    side,
                    cand.last_price,
                    reason,
                    cand.score,
                    strategy_mode=strat,
                )
                if success:
                    entered = True
                    snap = self.portfolio.snapshot()
                    break

            if entered and len(snap.positions) >= self.config.max_positions:
                break

    async def _open_position(
        self,
        inst_id: str,
        side: PositionSide,
        price: float,
        reason: str,
        score: float = 0.0,
        strategy_mode: StrategyMode | None = None,
    ) -> bool:
        snap = self.portfolio.snapshot()
        size_usdt = resolve_order_size_usdt(
            self.config,
            snap,
            open_positions=len(snap.positions),
        )
        if price <= 0:
            return False

        if self._is_live() and self._has_keys():
            await self._sync_live_if_needed()
            snap = self.portfolio.snapshot()
            size_usdt = resolve_order_size_usdt(
                self.config,
                snap,
                open_positions=len(snap.positions),
            )
            need_cost = entry_cost_usdt(self.config, size_usdt)
            if self.portfolio.available < need_cost:
                self._log(
                    "entry",
                    f"live entry blocked (available ${self.portfolio.available:.2f} < margin+fee ${need_cost:.2f}): {inst_id}",
                    "warn",
                )
                return False
            ok, msg, fill_price = await live_open(self.config, inst_id, side, size_usdt)
            if not ok:
                self._log("order", f"실거래 진입 실패: {msg}", "warn")
                return False
            price = fill_price
            await self._sync_live_if_needed()
            self._log("order", f"실거래 진입: {inst_id} {side.value} @ {price}", "ok")
            self._log("entry", f"진입 {inst_id} {side.value} (OKX 동기화)", "ok")
            return True

        if self.config.instrument_type == InstrumentType.SPOT:
            quantity = size_usdt / price
            notional = size_usdt
        else:
            rules = swap_sizing_rules(self.config, inst_id)
            quantity = swap_contract_count(
                size_usdt,
                price,
                rules.ct_val,
                rules.min_sz,
                rules.lot_sz,
            )
            notional = swap_notional_usdt(quantity, price, rules.ct_val)

        strat = strategy_mode or self.config.strategy_mode
        if strat == StrategyMode.BOTH:
            strat = StrategyMode.SCALP
        plan = await compute_dynamic_sl_tp(inst_id, price, side, strat, self.config)
        full_reason = f"{reason} | SL {plan.sl_pct}% TP {plan.tp_pct}% ({plan.method})"

        pos = self.portfolio.open_position(
            inst_id,
            side,
            quantity,
            price,
            self.config,
            full_reason,
            score,
            strategy_mode=strat,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            sl_pct=plan.sl_pct,
            tp_pct=plan.tp_pct,
            sl_tp_note=plan.method,
            notional_usdt=notional,
        )
        if pos:
            self._log(
                "entry",
                f"진입 {inst_id} {side.value} @ {price:.6g} | "
                f"명목 ${notional:,.0f} | SL {plan.sl_pct}% TP {plan.tp_pct}%",
                "ok",
            )
            return True
        need_cost = entry_cost_usdt(self.config, notional)
        self._log(
            "entry",
            f"entry blocked (available ${self.portfolio.available:,.2f} < margin+fee ${need_cost:,.2f}): {inst_id}",
            "warn",
        )
        return False

    async def _close_position(self, inst_id: str, reason: str) -> bool:
        pos = self.portfolio.positions.get(inst_id)
        if not pos:
            return False
        prices = await self.prices_map()
        price = prices.get(inst_id) or pos.current_price
        if price <= 0:
            price = pos.current_price

        if self._is_live() and self._has_keys():
            ok, msg = await live_close(self.config, inst_id, pos.side, pos.quantity)
            if not ok:
                self._log("order", f"실거래 청산 실패: {msg}", "warn")
                return False
            self._log("order", f"실거래 청산: {inst_id} — {reason}", "ok")
            await self._sync_live_if_needed()
            self._log("exit", f"청산 {inst_id} (OKX 동기화) — {reason}", "ok")
            return True

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

    async def set_position_sl_tp(
        self,
        inst_id: str,
        sl_pct: float,
        tp_pct: float,
    ) -> tuple[bool, str]:
        self.bind_portfolio()
        ok, msg = self.portfolio.set_sl_tp_manual(inst_id, sl_pct, tp_pct)
        if ok:
            pos = self.portfolio.positions.get(inst_id)
            side = pos.side.value if pos else ""
            self._log(
                "config",
                f"[수동 SL/TP] {inst_id} {side} — 손절 {sl_pct}% / 익절 {tp_pct}% (가격 도달 시 자동 청산)",
                "ok",
            )
            self._notify()
        return ok, msg

    async def set_position_auto_sl_tp_disabled(
        self,
        inst_id: str,
        disabled: bool,
    ) -> tuple[bool, str]:
        self.bind_portfolio()
        pos = self.portfolio.positions.get(inst_id)
        if not pos:
            return False, "포지션 없음"
        pos.auto_sl_tp_disabled = bool(disabled)
        self.portfolio.save()
        label = "사용 안 함" if disabled else "사용"
        self._log("config", f"[포지션 SL/TP 자동] {inst_id} {label}", "ok")
        self._notify()
        return True, "OK"

    async def reset_position_sl_tp_auto(self, inst_id: str) -> tuple[bool, str]:
        self.bind_portfolio()
        if not self.portfolio.clear_sl_tp_manual(inst_id):
            return False, "포지션 없음"
        pos = self.portfolio.positions.get(inst_id)
        if not pos or pos.entry_price <= 0:
            return False, "포지션 없음"
        pos.auto_sl_tp_disabled = False
        strat = pos.strategy_mode
        if strat == StrategyMode.BOTH:
            strat = StrategyMode.SCALP
        try:
            plan = await compute_dynamic_sl_tp(
                inst_id, pos.entry_price, pos.side, strat, self.config
            )
            self.portfolio.apply_sl_tp_plan(inst_id, plan)
        except Exception as e:
            return False, f"자동 SL/TP 갱신 실패: {e}"
        self._log("config", f"[자동 SL/TP] {inst_id} — 차트 기준으로 복귀", "ok")
        self._notify()
        return True, "자동 SL/TP로 복귀"

    async def reset_paper_portfolio(self, initial_balance: float | None = None) -> float:
        bal = initial_balance if initial_balance is not None else self.config.paper_initial_balance
        if bal <= 0:
            raise ValueError("초기자금은 0보다 커야 합니다")
        old_cfg = self.config.model_copy(deep=True)
        self.config.paper_initial_balance = bal
        bal_changes = format_config_changes(old_cfg, self.config)
        if bal_changes:
            self._log("config", "[모의투자 초기화] " + " | ".join(bal_changes))

        if self.bot.status.running:
            await self.stop_bot()

        prev_portfolio = self.portfolio
        self.portfolio = store.paper
        for inst_id in list(store.paper.positions.keys()):
            await self._close_position(inst_id, "초기화 청산")
        self.portfolio = prev_portfolio

        store.paper.reset(bal)
        self.bind_portfolio()
        self.candidates = []
        self._log("reset", f"모의투자 초기화 (${bal:,.0f})", "ok")
        self._notify()
        return bal

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
