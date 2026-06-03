"""Historical bar-by-bar backtest aligned with live entry/exit rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

from app.config import settings
from app.entry_signals import resolve_entry_side
from app.engine.exit_rules import should_exit
from app.engine.risk_manager import check_entry_allowed
from app.market.entry_analyzer import _analyze_closes
from app.models import (
    AppConfig,
    CoinCandidate,
    PortfolioSnapshot,
    Position,
    PositionSide,
    StrategyMode,
)
from app.strategy_utils import active_strategies, sl_tp_pcts
from app.backtest.models import (
    BacktestLogEntry,
    BacktestMetrics,
    BacktestRecommendation,
    BacktestScoreTrial,
    BacktestTrade,
)


def _utc_now() -> str:
    from app.models import utc_now_iso
    return utc_now_iso()


@dataclass
class _SimPos:
    inst_id: str
    side: PositionSide
    strategy: StrategyMode
    entry_bar: int
    entry_price: float
    quantity: float
    notional: float
    stop_loss: float
    take_profit: float
    sl_pct: float
    tp_pct: float
    trailing_high: float
    score: float


@dataclass
class _SimState:
    equity: float
    positions: dict[str, _SimPos] = field(default_factory=dict)
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


def _candles_to_arrays(candles: list[list]) -> tuple[np.ndarray, np.ndarray]:
    closes = np.array([float(c[4]) for c in candles])
    volumes = np.array([float(c[5]) for c in candles])
    return closes, volumes


def _change_pct(closes: np.ndarray, idx: int, lookback: int = 48) -> float:
    start = max(0, idx - lookback)
    if idx <= start:
        return 0.0
    base = closes[start]
    if base <= 0:
        return 0.0
    return (closes[idx] - base) / base * 100


def _build_candidate(
    inst_id: str,
    closes: np.ndarray,
    volumes: np.ndarray,
    idx: int,
    strategy: StrategyMode,
) -> CoinCandidate:
    window_c = closes[: idx + 1]
    window_v = volumes[: idx + 1]
    score, scalp_ok, swing_ok, outlook, reasons, rsi, trend, short_scalp, short_swing = (
        _analyze_closes(window_c, window_v, strategy)
    )
    change = _change_pct(closes, idx)
    if change < -4 and rsi >= 48:
        outlook = "short"
        short_scalp = True
        short_swing = trend == "down"
    return CoinCandidate(
        inst_id=inst_id,
        last_price=float(closes[idx]),
        change_24h_pct=round(change, 2),
        volume_24h_usdt=1e6,
        score=round(score, 1),
        scalp_ok=scalp_ok,
        swing_ok=swing_ok,
        short_scalp_ok=short_scalp,
        short_swing_ok=short_swing,
        outlook=outlook,
        reasons=reasons,
        rsi=round(rsi, 1),
        trend=trend,
    )


def _sl_tp_prices(entry: float, side: PositionSide, sl_pct: float, tp_pct: float) -> tuple[float, float]:
    sl_r, tp_r = sl_pct / 100, tp_pct / 100
    if side == PositionSide.LONG:
        return entry * (1 - sl_r), entry * (1 + tp_r)
    return entry * (1 + sl_r), entry * (1 - tp_r)


def _portfolio_snap(state: _SimState) -> PortfolioSnapshot:
    locked = sum(p.notional / max(1, 3) for p in state.positions.values())
    return PortfolioSnapshot(
        balance=state.equity,
        equity=state.equity,
        available=max(0, state.equity - locked),
        unrealized_pnl=0,
        realized_pnl=0,
        positions=[],
        trade_count=len(state.trades),
        win_rate=0,
    )


def _to_position(sim: _SimPos, price: float, config: AppConfig) -> Position:
    cost = sim.entry_price * sim.quantity if sim.quantity else sim.notional
    if sim.side == PositionSide.LONG:
        upnl = (price - sim.entry_price) * sim.quantity
    else:
        upnl = (sim.entry_price - price) * sim.quantity
    upnl_pct = upnl / cost * 100 if cost > 0 else 0
    return Position(
        id="bt",
        inst_id=sim.inst_id,
        side=sim.side,
        quantity=sim.quantity,
        entry_price=sim.entry_price,
        current_price=price,
        stop_loss=sim.stop_loss,
        take_profit=sim.take_profit,
        sl_pct=sim.sl_pct,
        tp_pct=sim.tp_pct,
        strategy_mode=sim.strategy,
        instrument_type=config.instrument_type,
        trailing_high=sim.trailing_high,
        unrealized_pnl=upnl,
        unrealized_pnl_pct=upnl_pct,
    )


def simulate_symbol(
    inst_id: str,
    candles: list[list],
    config: AppConfig,
    state: _SimState,
    logs: list[BacktestLogEntry],
    min_score_override: float | None = None,
) -> int:
    if len(candles) < 70:
        logs.append(BacktestLogEntry(ts=_utc_now(), level="warn", message=f"{inst_id}: 캔들 부족"))
        return 0

    closes, volumes = _candles_to_arrays(candles)
    cfg = config.model_copy(deep=True)
    if min_score_override is not None:
        cfg.min_score = min_score_override

    strat_list = active_strategies(cfg)
    if not strat_list:
        strat_list = [StrategyMode.SCALP]

    bar_count = 0
    for i in range(60, len(closes)):
        price = float(closes[i])
        bar_count += 1

        for iid in list(state.positions.keys()):
            if iid != inst_id:
                continue
            sim = state.positions[iid]
            pos = _to_position(sim, price, cfg)
            exit_flag, reason = should_exit(pos, cfg)
            if exit_flag:
                fee = sim.notional * settings.trading_fee_pct / 100 * 2
                if sim.side == PositionSide.LONG:
                    pnl = sim.notional * (price - sim.entry_price) / sim.entry_price
                else:
                    pnl = sim.notional * (sim.entry_price - price) / sim.entry_price
                pnl -= fee
                pnl_pct = pnl / sim.notional * 100 if sim.notional > 0 else 0
                state.trades.append(
                    BacktestTrade(
                        inst_id=inst_id,
                        side=sim.side.value,
                        strategy=sim.strategy.value,
                        entry_bar=sim.entry_bar,
                        exit_bar=i,
                        entry_price=sim.entry_price,
                        exit_price=price,
                        score=sim.score,
                        sl_pct=sim.sl_pct,
                        tp_pct=sim.tp_pct,
                        pnl_usdt=round(pnl, 2),
                        pnl_pct=round(pnl_pct, 2),
                        exit_reason=reason,
                    )
                )
                state.equity += pnl
                del state.positions[iid]
                logs.append(
                    BacktestLogEntry(
                        ts=_utc_now(),
                        level="info",
                        message=f"{inst_id} 청산 {reason} PnL {pnl:+.2f}",
                    )
                )

        if inst_id in state.positions:
            sim = state.positions[inst_id]
            if sim.side == PositionSide.LONG:
                sim.trailing_high = max(sim.trailing_high, price)
            else:
                sim.trailing_high = min(sim.trailing_high, price) if sim.trailing_high > 0 else price
            continue

        if len(state.positions) >= cfg.max_positions:
            continue

        for strat in strat_list:
            cand = _build_candidate(inst_id, closes, volumes, i, strat)
            side = resolve_entry_side(cfg, cand)
            if side is None:
                continue
            snap = _portfolio_snap(state)
            ok, msg = check_entry_allowed(cfg, snap, cand, strat, entry_side=side)
            if not ok:
                continue

            sl_pct, tp_pct = sl_tp_pcts(cfg, strat)
            sl, tp = _sl_tp_prices(price, side, sl_pct, tp_pct)
            notional = cfg.order_size_usdt
            state.positions[inst_id] = _SimPos(
                inst_id=inst_id,
                side=side,
                strategy=strat,
                entry_bar=i,
                entry_price=price,
                quantity=notional / price if price > 0 else 0,
                notional=notional,
                stop_loss=sl,
                take_profit=tp,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                trailing_high=price,
                score=cand.score,
            )
            logs.append(
                BacktestLogEntry(
                    ts=_utc_now(),
                    level="info",
                    message=(
                        f"{inst_id} 진입 {side.value} bar={i} score={cand.score:.0f} "
                        f"SL{sl_pct}% TP{tp_pct}%"
                    ),
                )
            )
            break

        state.equity_curve.append(state.equity)

    return bar_count


def run_simulation(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
    min_score_override: float | None = None,
) -> tuple[_SimState, int]:
    state = _SimState(equity=config.paper_initial_balance or settings.initial_balance)
    total_bars = 0
    for inst_id, candles in symbol_candles.items():
        logs.append(
            BacktestLogEntry(ts=_utc_now(), level="info", message=f"--- {inst_id} 시뮬레이션 ---")
        )
        total_bars += simulate_symbol(inst_id, candles, config, state, logs, min_score_override)

    for iid, sim in list(state.positions.items()):
        logs.append(
            BacktestLogEntry(
                ts=_utc_now(),
                level="warn",
                message=f"{iid} 미청산 포지션 (백테스트 종료 시점)",
            )
        )
    return state, total_bars


def _metrics_from_state(state: _SimState, bars: int, start_equity: float) -> BacktestMetrics:
    trades = state.trades
    wins = sum(1 for t in trades if t.pnl_usdt > 0)
    total_pnl = sum(t.pnl_usdt for t in trades)
    long_n = sum(1 for t in trades if t.side == "long")
    short_n = sum(1 for t in trades if t.side == "short")
    avg_score = sum(t.score for t in trades) / len(trades) if trades else 0.0

    max_dd = 0.0
    peak = start_equity
    for eq in state.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

    return BacktestMetrics(
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl / start_equity * 100, 2) if start_equity > 0 else 0,
        win_rate=round(wins / len(trades) * 100, 1) if trades else 0,
        trade_count=len(trades),
        long_trades=long_n,
        short_trades=short_n,
        avg_score_entries=round(avg_score, 1),
        max_drawdown_pct=round(max_dd, 2),
        bars_evaluated=bars,
    )


def optimize_min_score(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
) -> BacktestRecommendation:
    candidates = [45.0, 50.0, 55.0, 60.0, 65.0, 70.0]
    trials: list[BacktestScoreTrial] = []
    best_score = config.min_score
    best_pnl = float("-inf")

    logs.append(
        BacktestLogEntry(ts=_utc_now(), level="info", message="최소 점수 그리드 탐색 시작")
    )
    for ms in candidates:
        trial_logs: list[BacktestLogEntry] = []
        state, _ = run_simulation(config, symbol_candles, trial_logs, min_score_override=ms)
        pnl = sum(t.pnl_usdt for t in state.trades)
        wins = sum(1 for t in state.trades if t.pnl_usdt > 0)
        wr = wins / len(state.trades) * 100 if state.trades else 0
        long_e = sum(1 for t in state.trades if t.side == "long")
        short_e = sum(1 for t in state.trades if t.side == "short")
        trials.append(
            BacktestScoreTrial(
                min_score=ms,
                total_pnl=round(pnl, 2),
                win_rate=round(wr, 1),
                trades=len(state.trades),
                long_entries=long_e,
                short_entries=short_e,
            )
        )
        logs.append(
            BacktestLogEntry(
                ts=_utc_now(),
                level="info",
                message=f"min_score={ms} → PnL {pnl:+.2f} 거래 {len(state.trades)}건",
            )
        )
        if pnl > best_pnl or (pnl == best_pnl and len(state.trades) > 0):
            best_pnl = pnl
            best_score = ms

    reason = f"그리드 탐색 결과 PnL 최대 min_score={best_score} (${best_pnl:+.2f})"
    return BacktestRecommendation(min_score=best_score, reason=reason, trials=trials)


def build_result(
    config: AppConfig,
    symbols: list[str],
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
    optimize: bool = True,
) -> BacktestResult:
    rid = str(uuid.uuid4())[:8]
    started = _utc_now()
    start_equity = config.paper_initial_balance or settings.initial_balance

    logs.insert(
        0,
        BacktestLogEntry(
            ts=started,
            level="info",
            message=f"백테스트 시작 id={rid} 종목 {len(symbols)}개",
        ),
    )

    recommendation = None
    if optimize:
        recommendation = optimize_min_score(config, symbol_candles, logs)
        logs.append(
            BacktestLogEntry(
                ts=_utc_now(),
                level="ok",
                message=f"추천 min_score={recommendation.min_score} — {recommendation.reason}",
            )
        )

    min_run = recommendation.min_score if recommendation else config.min_score
    state, bars = run_simulation(config, symbol_candles, logs, min_score_override=min_run)
    metrics = _metrics_from_state(state, bars, start_equity)

    finished = _utc_now()
    logs.append(
        BacktestLogEntry(
            ts=finished,
            level="ok",
            message=(
                f"완료 PnL {metrics.total_pnl:+.2f} ({metrics.total_pnl_pct:+.1f}%) "
                f"거래 {metrics.trade_count} 승률 {metrics.win_rate}%"
            ),
        )
    )

    candle_bars = max((len(c) for c in symbol_candles.values()), default=0)
    return BacktestResult(
        id=rid,
        status="done",
        started_at=started,
        finished_at=finished,
        strategy_mode=config.strategy_mode.value,
        symbols=symbols,
        candle_bars=candle_bars,
        params_snapshot={
            "min_score": config.min_score,
            "min_score_applied": min_run,
            "max_positions": config.max_positions,
            "order_size_usdt": config.order_size_usdt,
            "position_side": config.position_side.value,
            "leverage": config.leverage,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
        },
        metrics=metrics,
        recommendation=recommendation,
        trades=state.trades,
        logs=logs,
    )
