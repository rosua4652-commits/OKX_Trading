"""Core trading engine ??scan, analyze, enter, exit."""

from __future__ import annotations

import asyncio
import logging
import time
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
from app.market.okx_client import get_okx_client
from app.market.scanner import scan_market, top_symbols
from app.models import (
    AppConfig,
    BotState,
    CoinCandidate,
    InstrumentType,
    ManualOrderRequest,
    PendingOrder,
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
        self._last_live_sync = 0.0
        self._last_dynamic_sl_tp_sync = 0.0
        self._exit_check_task: asyncio.Task | None = None
        self._live_sync_task: asyncio.Task | None = None
        self._reentry_watchlist: dict[str, PositionSide] = {}
        self._pending_orders_cache_at = 0.0
        self._pending_orders_cache: list[PendingOrder] = []

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

    def _mark_reentry_watch(self, inst_id: str, side: PositionSide, reason: str, pnl: float | None = None) -> None:
        is_loss_exit = (pnl is not None and pnl < 0) or ("손절" in reason) or ("stop" in reason.lower())
        if not is_loss_exit:
            return
        self._reentry_watchlist[inst_id] = side
        self._log("risk", f"{inst_id} 손절 후 반등/추세 회복 확인 전까지 같은 방향 재진입 보류", "warn")

    def _ema_list(self, values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        out = [values[0]]
        for v in values[1:]:
            out.append(alpha * v + (1 - alpha) * out[-1])
        return out

    def _sma_tail(self, values: list[float], period: int, idx: int) -> float:
        start = max(0, idx - period + 1)
        window = values[start : idx + 1]
        return sum(window) / len(window) if window else 0.0

    def _macd_hist(self, closes: list[float]) -> list[float]:
        if len(closes) < 35:
            return []
        ema12 = self._ema_list(closes, 12)
        ema26 = self._ema_list(closes, 26)
        macd = [a - b for a, b in zip(ema12, ema26)]
        signal = self._ema_list(macd, 9)
        return [m - s for m, s in zip(macd, signal)]

    async def _trend_scale_signal(self, pos) -> tuple[bool, str]:
        strat_key = "swing" if pos.strategy_mode == StrategyMode.SWING else "scalp"
        candles = await market.candles(pos.inst_id, strat_key, limit=80)
        if len(candles) < 55:
            return False, "캔들 부족"
        try:
            opens = [float(c[1]) for c in candles]
            highs = [float(c[2]) for c in candles]
            lows = [float(c[3]) for c in candles]
            closes = [float(c[4]) for c in candles]
            volumes = [float(c[5]) if len(c) > 5 else 0.0 for c in candles]
        except (TypeError, ValueError, IndexError):
            return False, "캔들 파싱 실패"

        ema20 = self._ema_list(closes, 20)
        ema50 = self._ema_list(closes, 50)
        hist = self._macd_hist(closes)
        if len(hist) < 4:
            return False, "MACD 부족"
        vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
        vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
        body = abs(closes[-1] - opens[-1])
        candle_range = max(highs[-1] - lows[-1], closes[-1] * 0.0001)
        strong_body = body / candle_range >= 0.45
        last_scale = pos.last_scale_price or pos.entry_price

        if pos.side == PositionSide.LONG:
            trend_ok = closes[-1] > ema20[-1] > ema50[-1] and ema20[-1] > ema20[-4]
            macd_ok = hist[-1] > 0 and hist[-1] > hist[-2] > hist[-3]
            candle_ok = closes[-1] > opens[-1] and closes[-1] >= highs[-1] - candle_range * 0.25
            spacing_ok = last_scale <= 0 or closes[-1] >= last_scale * 1.004
            ok = trend_ok and macd_ok and candle_ok and strong_body and vol_ratio >= 1.5 and spacing_ok
        else:
            trend_ok = closes[-1] < ema20[-1] < ema50[-1] and ema20[-1] < ema20[-4]
            macd_ok = hist[-1] < 0 and hist[-1] < hist[-2] < hist[-3]
            candle_ok = closes[-1] < opens[-1] and closes[-1] <= lows[-1] + candle_range * 0.25
            spacing_ok = last_scale <= 0 or closes[-1] <= last_scale * 0.996
            ok = trend_ok and macd_ok and candle_ok and strong_body and vol_ratio >= 1.5 and spacing_ok

        reason = f"체결량 {vol_ratio:.1f}배 · EMA20/50 추세 · MACD 강화"
        return ok, reason

    async def _trend_break_signal(self, pos) -> tuple[bool, str]:
        if not self.config.trend_scale_in:
            return False, ""
        if pos.unrealized_pnl_pct < max(2.0, self.config.scale_in_min_pnl_pct * 0.7):
            return False, ""
        strat_key = "swing" if pos.strategy_mode == StrategyMode.SWING else "scalp"
        candles = await market.candles(pos.inst_id, strat_key, limit=80)
        if len(candles) < 55:
            return False, ""
        try:
            opens = [float(c[1]) for c in candles]
            closes = [float(c[4]) for c in candles]
            volumes = [float(c[5]) if len(c) > 5 else 0.0 for c in candles]
        except (TypeError, ValueError, IndexError):
            return False, ""

        ema20 = self._ema_list(closes, 20)
        hist = self._macd_hist(closes)
        if len(hist) < 4:
            return False, ""
        vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
        vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
        confirm_bars = max(1, min(6, int(self.config.trend_exit_confirm_bars or 3)))
        recent = range(len(closes) - confirm_bars, len(closes))

        if pos.side == PositionSide.LONG:
            macd_turn = hist[-1] < hist[-2] < hist[-3] and hist[-1] < 0
            candle_break = (
                all(closes[i] < ema20[i] for i in recent)
                and closes[-1] < opens[-1]
            )
        else:
            macd_turn = hist[-1] > hist[-2] > hist[-3] and hist[-1] > 0
            candle_break = (
                all(closes[i] > ema20[i] for i in recent)
                and closes[-1] > opens[-1]
            )

        if pos.unrealized_pnl > 0 and macd_turn and candle_break and vol_ratio >= 1.2:
            return True, f"추세 꺾임/MACD 반전 ({confirm_bars}캔들 확인 · 거래량 {vol_ratio:.1f}배)"
        return False, ""

    async def _reentry_confirmed(
        self,
        inst_id: str,
        side: PositionSide,
        strategy: StrategyMode,
    ) -> bool:
        strat_key = "swing" if strategy == StrategyMode.SWING else "scalp"
        candles = await market.candles(inst_id, strat_key, limit=80)
        if len(candles) < 35:
            return False
        try:
            highs = [float(c[2]) for c in candles]
            lows = [float(c[3]) for c in candles]
            closes = [float(c[4]) for c in candles]
            opens = [float(c[1]) for c in candles]
            volumes = [float(c[5]) if len(c) > 5 else 0.0 for c in candles]
        except (TypeError, ValueError, IndexError):
            return False

        hlc3 = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        esa = self._ema_list(hlc3, 10)
        dev = self._ema_list([abs(v - e) for v, e in zip(hlc3, esa)], 10)
        ci = [(v - e) / (0.015 * d) if d > 0 else 0.0 for v, e, d in zip(hlc3, esa, dev)]
        wt1 = self._ema_list(ci, 21)
        wt2 = [self._sma_tail(wt1, 4, i) for i in range(len(wt1))]
        if len(wt1) < 3 or len(wt2) < 3:
            return False

        if side == PositionSide.LONG:
            wave_cross = wt1[-2] <= wt2[-2] and wt1[-1] > wt2[-1]
            wave_recover = wt1[-1] > wt1[-2] > wt1[-3] and wt1[-1] < 20
            candle_rebound = closes[-1] > opens[-1] and closes[-1] > highs[-2]
            ema_reclaim = closes[-1] > self._ema_list(closes, 12)[-1]
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            vol_ok = volumes[-1] > vol_avg * 1.15 if vol_avg > 0 else True
            return (wave_cross or wave_recover) and (candle_rebound or ema_reclaim) and vol_ok

        wave_cross = wt1[-2] >= wt2[-2] and wt1[-1] < wt2[-1]
        wave_rollover = wt1[-1] < wt1[-2] < wt1[-3] and wt1[-1] > -20
        candle_reject = closes[-1] < opens[-1] and closes[-1] < lows[-2]
        ema_reject = closes[-1] < self._ema_list(closes, 12)[-1]
        vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
        vol_ok = volumes[-1] > vol_avg * 1.15 if vol_avg > 0 else True
        return (wave_cross or wave_rollover) and (candle_reject or ema_reject) and vol_ok

    async def pending_orders(self) -> list[PendingOrder]:
        if not self._is_live() or not self._has_keys():
            return []
        now = time.monotonic()
        if now - self._pending_orders_cache_at < 5:
            return self._pending_orders_cache
        client = get_okx_client(
            self.config.okx_api_key,
            self.config.okx_api_secret,
            self.config.okx_passphrase,
            self.config.okx_flag,
        )
        inst_type = "SPOT" if self.config.instrument_type == InstrumentType.SPOT else "SWAP"
        out: list[PendingOrder] = []
        rows = await asyncio.to_thread(client.get_pending_orders, inst_type=inst_type)
        for row in rows:
            try:
                out.append(
                    PendingOrder(
                        inst_id=row.get("instId", ""),
                        ord_id=row.get("ordId", ""),
                        side=row.get("side", ""),
                        pos_side=row.get("posSide", ""),
                        order_type=row.get("ordType", ""),
                        price=float(row.get("px") or 0),
                        size=float(row.get("sz") or 0),
                        filled_size=float(row.get("accFillSz") or 0),
                        state=row.get("state", ""),
                        ts=str(row.get("cTime") or row.get("uTime") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        self._pending_orders_cache_at = now
        self._pending_orders_cache = out
        return out

    async def prices_map(self) -> dict[str, float]:
        return await market.price_map(self.config.instrument_type)

    async def position_prices_map(self) -> dict[str, float]:
        ids = list(self.portfolio.positions.keys())
        if not ids:
            return {}
        return await market.prices_for(ids)

    async def _refresh_dynamic_sl_tp_all(self) -> None:
        now = time.monotonic()
        if now - self._last_dynamic_sl_tp_sync < 30:
            return
        self._last_dynamic_sl_tp_sync = now
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

    async def _sync_live_if_needed(self, force: bool = False, include_fills: bool = True) -> None:
        if not self._is_live():
            self._portfolio_sync_message = ""
            return
        if not self._has_keys():
            self._portfolio_sync_message = "실거래 API 키를 설정/저장하세요"
            return
        now = time.monotonic()
        if not force and now - self._last_live_sync < 2:
            return
        self._last_live_sync = now
        ok, msg = await asyncio.to_thread(
            sync_live_portfolio,
            self.portfolio,
            self.config,
            include_fills=include_fills,
        )
        self._portfolio_sync_message = msg
        if ok:
            logger.debug(msg)
        else:
            self._log("sync", msg, "warn")

    def _schedule_live_sync(self, include_fills: bool = False) -> None:
        if not self._is_live() or not self._has_keys():
            return
        if self._live_sync_task and not self._live_sync_task.done():
            return
        self._live_sync_task = asyncio.create_task(
            self._sync_live_if_needed(force=False, include_fills=include_fills)
        )

    def _schedule_exit_check(self) -> None:
        if not self.portfolio.positions:
            return
        if self._exit_check_task and not self._exit_check_task.done():
            return
        self._exit_check_task = asyncio.create_task(self._check_exits())

    async def get_status(self) -> dict:
        self.bind_portfolio()
        if self._is_live():
            self._schedule_live_sync(include_fills=False)
        await self._refresh_dynamic_sl_tp_all()
        prices = await self.position_prices_map()
        if not self._is_live():
            self.portfolio.update_prices(prices)
        elif self.portfolio.positions:
            self.portfolio.update_prices(prices)
        self._schedule_exit_check()
        snap = self.portfolio.snapshot()
        linked = False
        if self._has_keys() and self._link_message and "실패" not in self._link_message and "오류" not in self._link_message:
            linked = "연결" in self._link_message or self._link_message.lower().startswith("ok")
        pending_orders = await self.pending_orders()
        out: dict = {
            "config": config_for_client(self.config),
            "bot": self.bot.model_dump(),
            "portfolio": snap.model_dump(),
            "candidates": [c.model_dump() for c in self.candidates[:20]],
            "linked": linked,
            "link_message": self._link_message,
            "portfolio_source": "okx" if self._is_live() else "paper",
            "portfolio_sync_message": self._portfolio_sync_message,
            "pending_orders": [o.model_dump() for o in pending_orders],
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
                self._log("error", f"루프 오류: {e}", "warn")
            await asyncio.sleep(min(2, settings.scan_interval_sec))

    async def _tick(self) -> None:
        self.bind_portfolio()
        if self._is_live():
            await self._sync_live_if_needed()
        self.bot.status.scan_count += 1
        self.bot.status.last_scan = utc_now_iso()
        self._log("scan", f"시장 스캔 #{self.bot.status.scan_count}")

        await self._check_exits()
        await self._scale_in_positions()

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
            f"후보 {len(analyzed)} (롱 {n_long} / 숏 {n_short}) · 진입모드={side_mode}",
        )

        if self.config.auto_invest:
            await self._auto_enter(analyzed)

        self._notify()

    async def _check_exits(self) -> None:
        prices = await self.position_prices_map()
        self.portfolio.update_prices(prices)

        for inst_id in list(self.portfolio.positions.keys()):
            pos = self.portfolio.positions.get(inst_id)
            if not pos:
                continue
            trend_exit, trend_reason = await self._trend_break_signal(pos)
            if trend_exit:
                await self._close_position(inst_id, f"추세 이탈 청산 - {trend_reason}")
                continue
            exit_flag, reason = should_exit(pos, self.config)
            if exit_flag:
                await self._close_position(inst_id, reason)

    async def _scale_in_positions(self) -> None:
        if not self.config.trend_scale_in or self.config.max_scale_ins <= 0:
            return
        if not self.portfolio.positions:
            return
        for inst_id in list(self.portfolio.positions.keys()):
            pos = self.portfolio.positions.get(inst_id)
            if not pos:
                continue
            if pos.auto_sl_tp_disabled:
                continue
            if pos.scale_in_count >= self.config.max_scale_ins:
                continue
            if pos.unrealized_pnl_pct < self.config.scale_in_min_pnl_pct:
                continue
            ok, reason = await self._trend_scale_signal(pos)
            if not ok:
                continue
            await self._scale_in_position(pos, reason)

    async def _scale_in_position(self, pos, signal_reason: str) -> bool:
        snap = self.portfolio.snapshot()
        base_size = resolve_order_size_usdt(
            self.config,
            snap,
            open_positions=len(snap.positions),
        )
        size_pct = max(5.0, min(100.0, self.config.scale_in_size_pct))
        size_usdt = base_size * size_pct / 100
        if size_usdt <= 0 or pos.current_price <= 0:
            return False

        reason = f"추세추종 추가진입 #{pos.scale_in_count + 1} | {signal_reason}"
        if self._is_live() and self._has_keys():
            need_cost = entry_cost_usdt(self.config, size_usdt)
            if self.portfolio.available < need_cost:
                self._log("entry", f"추가진입 보류: 가능 ${self.portfolio.available:.2f} < 필요 ${need_cost:.2f}", "warn")
                return False
            ok, msg, _ = await live_open(self.config, pos.inst_id, pos.side, size_usdt)
            if not ok:
                self._log("order", f"실거래 추가진입 실패: {msg}", "warn")
                return False
            pos.scale_in_count += 1
            pos.last_scale_price = pos.current_price
            self.portfolio.save()
            self._log("entry", f"{pos.inst_id} {pos.side.value} 추가진입 주문 접수 | {reason}", "ok")
            await self._sync_live_if_needed(force=True)
            return True

        price = pos.current_price
        if self.config.instrument_type == InstrumentType.SPOT:
            quantity = size_usdt / price
            notional = size_usdt
        else:
            rules = swap_sizing_rules(self.config, pos.inst_id)
            quantity = swap_contract_count(
                size_usdt,
                price,
                rules.ct_val,
                rules.min_sz,
                rules.lot_sz,
            )
            notional = swap_notional_usdt(quantity, price, rules.ct_val)

        updated = self.portfolio.add_to_position(
            pos.inst_id,
            quantity,
            price,
            self.config,
            reason,
            notional_usdt=notional,
        )
        if not updated:
            need_cost = entry_cost_usdt(self.config, notional)
            self._log("entry", f"추가진입 보류: 가능 ${self.portfolio.available:.2f} < 필요 ${need_cost:.2f}", "warn")
            return False
        self._log(
            "entry",
            f"{pos.inst_id} {pos.side.value} 추가진입 @ {price:.6g} | 명목 ${notional:,.2f} | {signal_reason}",
            "ok",
        )
        return True

    def _resolve_entry_side(self, cand: CoinCandidate) -> PositionSide | None:
        return resolve_entry_side(self.config, cand)

    def _log_candidate_decisions(self, candidates: list[CoinCandidate], limit: int = 8) -> None:
        snap = self.portfolio.snapshot()
        for cand in candidates[:limit]:
            self._log(
                "decision",
                (
                    f"{cand.inst_id} 후보 평가: 가격 ${cand.last_price:.8g} · "
                    f"점수 {cand.score:.1f}/{self.config.min_score:g} · "
                    f"판단 {cand.outlook or '-'} · 추세 {cand.trend or '-'} · "
                    f"RSI {cand.rsi:.1f} · 24h거래량 ${cand.volume_24h_usdt:,.0f} · "
                    f"근거 {', '.join(cand.reasons[:4]) or '-'}"
                ),
            )
            if any(p.inst_id == cand.inst_id for p in snap.positions):
                self._log("decision", f"{cand.inst_id} 진입 거절: 이미 보유 중")
                continue
            side = self._resolve_entry_side(cand)
            if side is None:
                self._log("decision", f"{cand.inst_id} 진입 거절: 설정/신호 기준 방향 없음")
                continue
            for strat in active_strategies(self.config):
                ok, msg = check_entry_allowed(self.config, snap, cand, strat, entry_side=side)
                label = "단타" if strat == StrategyMode.SCALP else "장타"
                if ok:
                    self._log(
                        "decision",
                        f"{cand.inst_id} {label} {side.value} 진입 가능: 점수 {cand.score:.1f}, min_score {self.config.min_score:g}",
                        "ok",
                    )
                else:
                    self._log("decision", f"{cand.inst_id} {label} {side.value} 진입 거절: {msg}")

    async def _auto_enter(self, candidates: list[CoinCandidate]) -> None:
        snap = self.portfolio.snapshot()
        detail_budget = 8
        for cand in candidates:
            detail = detail_budget > 0
            if detail:
                detail_budget -= 1
                self._log(
                    "decision",
                    (
                        f"{cand.inst_id} 후보 평가: 가격 ${cand.last_price:.8g} · "
                        f"점수 {cand.score:.1f}/{self.config.min_score:g} · "
                        f"판단 {cand.outlook or '-'} · 추세 {cand.trend or '-'} · "
                        f"RSI {cand.rsi:.1f} · 24h거래량 ${cand.volume_24h_usdt:,.0f} · "
                        f"근거 {', '.join(cand.reasons[:4]) or '-'}"
                    ),
                )
            if any(p.inst_id == cand.inst_id for p in snap.positions):
                if detail:
                    self._log("decision", f"{cand.inst_id} 진입 거절: 이미 보유 중")
                continue

            side = self._resolve_entry_side(cand)
            if side is None:
                if detail:
                    self._log("decision", f"{cand.inst_id} 진입 거절: 설정/신호 기준 방향 없음")
                continue
            watched_side = self._reentry_watchlist.get(cand.inst_id)
            if watched_side == side:
                if not await self._reentry_confirmed(cand.inst_id, side, self.config.strategy_mode):
                    self._log("risk", f"{cand.inst_id} 손절 후 반등 확인 전이라 재진입 보류")
                    continue
                self._reentry_watchlist.pop(cand.inst_id, None)
                self._log("risk", f"{cand.inst_id} 반등/웨이브 확인, 재진입 허용", "ok")

            entered = False
            for strat in active_strategies(self.config):
                ok, msg = check_entry_allowed(
                    self.config, snap, cand, strat, entry_side=side
                )
                if not ok:
                    if detail:
                        label = "단타" if strat == StrategyMode.SCALP else "장타"
                        self._log(
                            "decision",
                            f"{cand.inst_id} {label} {side.value} 진입 거절: {msg}",
                        )
                    continue

                label = "단타" if strat == StrategyMode.SCALP else "장타"
                dir_label = "숏" if side == PositionSide.SHORT else "롱"
                if detail:
                    self._log(
                        "decision",
                        (
                            f"{cand.inst_id} {label} {dir_label} 진입 통과: "
                            f"점수 {cand.score:.1f}, min_score {self.config.min_score:g}, "
                            f"주문크기 계산 후 실행"
                        ),
                        "ok",
                    )
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
                if detail:
                    self._log("decision", f"{cand.inst_id} 주문 실행 실패: 주문/잔고/거래소 조건 확인", "warn")

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
        order_type: str = "market",
        limit_price: float = 0.0,
    ) -> bool:
        snap = self.portfolio.snapshot()
        size_usdt = resolve_order_size_usdt(
            self.config,
            snap,
            open_positions=len(snap.positions),
        )
        if price <= 0:
            return False
        need_cost_preview = entry_cost_usdt(self.config, size_usdt)
        self._log(
            "decision",
            (
                f"{inst_id} 주문 준비: mode={self.config.trade_mode.value} · "
                f"방향={side.value} · 명목 ${size_usdt:,.2f} · "
                f"필요증거금+수수료 ${need_cost_preview:,.2f} · "
                f"가용 ${self.portfolio.available:,.2f} · 레버 {self.config.leverage}x"
            ),
        )

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
                    "decision",
                    f"{inst_id} 실거래 진입 거절: 가용 ${self.portfolio.available:.2f} < 필요 ${need_cost:.2f}",
                    "warn",
                )
                return False
            ok, msg, fill_price = await live_open(
                self.config,
                inst_id,
                side,
                size_usdt,
                order_type=order_type,
                limit_price=limit_price,
            )
            if not ok:
                self._log("order", f"실거래 진입 실패: {inst_id} {side.value} · {msg}", "warn")
                return False
            price = fill_price
            await self._sync_live_if_needed()
            if order_type == "limit":
                self._log("order", f"실거래 지정가 주문 접수: {inst_id} {side.value} @ {price} ({msg})", "ok")
                self._log("entry", f"지정가 주문 접수 {inst_id} {side.value} (체결 후 OKX 동기화)", "ok")
            else:
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
            "decision",
            f"{inst_id} 모의 진입 거절: 가용 ${self.portfolio.available:,.2f} < 필요 ${need_cost:,.2f}",
            "warn",
        )
        return False

    async def _close_position(self, inst_id: str, reason: str) -> bool:
        pos = self.portfolio.positions.get(inst_id)
        if not pos:
            return False
        prices = await self.position_prices_map()
        price = prices.get(inst_id) or pos.current_price
        if price <= 0:
            price = pos.current_price

        if self._is_live() and self._has_keys():
            ok, msg = await live_close(self.config, inst_id, pos.side, pos.quantity)
            if not ok:
                self._log("order", f"live close failed: {msg}", "warn")
                return False
            self._log("order", f"live close accepted: {inst_id} - {reason}", "ok")
            trade = self.portfolio.close_position(inst_id, price, reason)
            await self._sync_live_if_needed()
            if trade:
                self._mark_reentry_watch(inst_id, pos.side, reason, trade.pnl)
                self._log(
                    "exit",
                    f"close {inst_id} PnL={trade.pnl:+.2f} ({trade.pnl_pct:+.1f}%) - {reason}",
                    "ok" if trade.pnl >= 0 else "warn",
                )
            else:
                self._log("exit", f"close {inst_id} synced from OKX - {reason}", "ok")
            return True

        trade = self.portfolio.close_position(inst_id, price, reason)
        if trade:
            self._mark_reentry_watch(inst_id, pos.side, reason, trade.pnl)
            self._log(
                "exit",
                f"close {inst_id} PnL={trade.pnl:+.2f} ({trade.pnl_pct:+.1f}%) - {reason}",
                "ok" if trade.pnl >= 0 else "warn",
            )
            return True
        return False

    async def manual_order(self, req: ManualOrderRequest) -> tuple[bool, str]:
        side = req.side
        order_type = "limit" if req.order_type == "limit" else "market"
        ticker = await market.ticker(req.inst_id)
        if not ticker:
            return False, "시세 없음"
        ticker_price = float(ticker.get("last", 0))
        price = req.price if order_type == "limit" and req.price > 0 else ticker_price
        if price <= 0:
            return False, "가격 오류"
        old_size = self.config.order_size_usdt
        old_lev = self.config.leverage
        self.config.order_size_usdt = req.size_usdt
        self.config.leverage = req.leverage
        reason = "수동 지정가 주문" if order_type == "limit" else "수동 시장가 주문"
        ok = await self._open_position(
            req.inst_id,
            side,
            price,
            reason,
            order_type=order_type,
            limit_price=price,
        )
        self.config.order_size_usdt = old_size
        self.config.leverage = old_lev
        self._notify()
        if ok and order_type == "limit" and self._is_live():
            return True, "지정가 주문 접수 완료. 체결되면 포지션에 표시됩니다"
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
                f"[수동 SL/TP] {inst_id} {side} 손절 {sl_pct}% / 익절 {tp_pct}% (가격 도달 시 자동 청산)",
                "ok",
            )
            self._notify()
        return ok, msg

    async def set_position_auto_sl_tp_disabled(
        self,
        inst_id: str,
        disabled: bool | None = None,
        sl_disabled: bool | None = None,
        tp_disabled: bool | None = None,
    ) -> tuple[bool, str]:
        self.bind_portfolio()
        pos = self.portfolio.positions.get(inst_id)
        if not pos:
            return False, "포지션 없음"
        if disabled is not None:
            pos.auto_sl_tp_disabled = bool(disabled)
            pos.auto_sl_disabled = bool(disabled)
            pos.auto_tp_disabled = bool(disabled)
        if sl_disabled is not None:
            pos.auto_sl_disabled = bool(sl_disabled)
        if tp_disabled is not None:
            pos.auto_tp_disabled = bool(tp_disabled)
        pos.auto_sl_tp_disabled = bool(pos.auto_sl_disabled and pos.auto_tp_disabled)
        self.portfolio.save()
        self._log(
            "config",
            f"[포지션 손익절] {inst_id} 손절 {'OFF' if pos.auto_sl_disabled else 'ON'} / "
            f"익절 {'OFF' if pos.auto_tp_disabled else 'ON'}",
            "ok",
        )
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
        pos.auto_sl_disabled = False
        pos.auto_tp_disabled = False
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
        self._log("config", f"[자동 SL/TP] {inst_id} 백테스트/차트 기준으로 복구", "ok")
        self._notify()
        return True, "자동 SL/TP로 복구"

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
        self._log("reset", f"紐⑥쓽?ъ옄 珥덇린??(${bal:,.0f})", "ok")
        self._notify()
        return bal

    async def close_all(self) -> int:
        count = 0
        for inst_id in list(self.portfolio.positions.keys()):
            if await self._close_position(inst_id, "?꾨웾 泥?궛"):
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
        self._log_candidate_decisions(self.candidates)
        self._notify()
        return self.candidates
