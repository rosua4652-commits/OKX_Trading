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
    InstrumentType,
    PortfolioSnapshot,
    Position,
    PositionSide,
    PositionSideMode,
    StrategyMode,
)
from app.order_sizing import resolve_order_size_usdt
from app.strategy_utils import active_strategies, sl_tp_pcts
from app.backtest.candles_util import build_symbol_charts
from app.backtest.zone_walkforward import evaluate_zone_walkforward
from app.backtest.models import (
    BacktestDirectionTrial,
    BacktestLogEntry,
    BacktestMetrics,
    BacktestRecommendation,
    BacktestResult,
    BacktestScoreTrial,
    BacktestSlTpTrial,
    BacktestTrade,
)

SCORE_GRID = [45.0, 50.0, 55.0, 60.0, 65.0, 70.0]
WINDOW_RATIOS = [1.0, 0.75, 0.5]
SL_GRID = [4.0, 5.0, 6.0, 7.0, 8.0, 10.0]
TP_GRID = [5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 14.0]

# 전략별 TP 상한: 백테스트 승률이 아무리 높아도 이 이상은 추천하지 않음
TP_MAX_BY_STRATEGY: dict[StrategyMode, float] = {
    StrategyMode.SCALP: 10.0,
    StrategyMode.SWING: 18.0,
    StrategyMode.BOTH: 10.0,
}


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
    scale_in_count: int = 0
    last_scale_price: float = 0.0


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


def _slice_candles(candles: list[list], window_ratio: float) -> list[list]:
    if window_ratio >= 0.99 or len(candles) < 80:
        return candles
    keep = max(70, int(len(candles) * window_ratio))
    return candles[-keep:]


def _flip_side(side: PositionSide | None) -> PositionSide | None:
    if side == PositionSide.LONG:
        return PositionSide.SHORT
    if side == PositionSide.SHORT:
        return PositionSide.LONG
    return None


def _config_for_direction(config: AppConfig, direction: str | None) -> AppConfig:
    cfg = config.model_copy(deep=True)
    if direction == "long_only":
        cfg.position_side = PositionSideMode.LONG
    elif direction == "short_only":
        cfg.position_side = PositionSideMode.SHORT
    return cfg


def _record_close(
    sim: _SimPos,
    inst_id: str,
    price: float,
    bar_i: int,
    state: _SimState,
    logs: list[BacktestLogEntry],
    reason: str,
    leverage: int = 1,
) -> None:
    fee = sim.notional * settings.trading_fee_pct / 100 * 2
    if sim.side == PositionSide.LONG:
        pnl = sim.notional * (price - sim.entry_price) / sim.entry_price
    else:
        pnl = sim.notional * (sim.entry_price - price) / sim.entry_price
    pnl -= fee
    lev = max(1, leverage)
    margin = sim.notional / lev
    pnl_pct = pnl / margin * 100 if margin > 0 else 0
    state.trades.append(
        BacktestTrade(
            inst_id=inst_id,
            side=sim.side.value,
            strategy=sim.strategy.value,
            entry_bar=sim.entry_bar,
            exit_bar=bar_i,
            entry_price=sim.entry_price,
            exit_price=price,
            score=sim.score,
            sl_pct=sim.sl_pct,
            tp_pct=sim.tp_pct,
            notional_usdt=round(sim.notional, 2),
            margin_usdt=round(margin, 2),
            fee_usdt=round(fee, 2),
            pnl_usdt=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            exit_reason=reason,
        )
    )
    state.equity += pnl
    logs.append(
        BacktestLogEntry(
            ts=_utc_now(),
            level="info",
            message=(
                f"{inst_id} 청산 {reason} | 투입 ${sim.notional:,.0f} "
                f"→ 손익 {pnl:+.2f} USDT ({pnl_pct:+.2f}%)"
            ),
        )
    )


def _close_open_positions(
    symbol_candles: dict[str, list[list]],
    state: _SimState,
    logs: list[BacktestLogEntry],
    leverage: int = 1,
) -> None:
    for iid, sim in list(state.positions.items()):
        candles = symbol_candles.get(iid)
        if not candles:
            continue
        last_i = len(candles) - 1
        price = float(candles[last_i][4])
        _record_close(sim, iid, price, last_i, state, logs, "백테스트 종료 청산", leverage)
        del state.positions[iid]


def _sl_tp_prices(
    entry: float,
    side: PositionSide,
    sl_pct: float,
    tp_pct: float,
    leverage: int = 1,
) -> tuple[float, float]:
    lev = max(1, leverage)
    sl_r, tp_r = (sl_pct / lev) / 100, (tp_pct / lev) / 100
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
    margin = cost / max(1, config.leverage) if config.instrument_type != InstrumentType.SPOT else cost
    upnl_pct = upnl / margin * 100 if margin > 0 else 0
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
        notional_usdt=sim.notional,
        scale_in_count=sim.scale_in_count,
        last_scale_price=sim.last_scale_price or sim.entry_price,
        unrealized_pnl=upnl,
        unrealized_pnl_pct=upnl_pct,
    )


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2 / (period + 1)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _macd_hist(closes: np.ndarray) -> np.ndarray:
    if len(closes) < 35:
        return np.array([])
    macd = _ema(closes, 12) - _ema(closes, 26)
    return macd - _ema(macd, 9)


def _trend_break_signal_bt(
    sim: _SimPos,
    candles: list[list],
    idx: int,
    cfg: AppConfig,
) -> tuple[bool, str]:
    if not cfg.trend_scale_in:
        return False, ""
    window = candles[: idx + 1]
    if len(window) < 55:
        return False, ""
    opens = np.array([float(c[1]) for c in window])
    closes = np.array([float(c[4]) for c in window])
    volumes = np.array([float(c[5]) for c in window])
    pos = _to_position(sim, float(closes[-1]), cfg)
    if pos.unrealized_pnl_pct < max(1.0, cfg.scale_in_min_pnl_pct * 0.35):
        return False, ""
    ema20 = _ema(closes, 20)
    hist = _macd_hist(closes)
    if len(hist) < 4:
        return False, ""
    confirm_bars = max(1, min(6, int(cfg.trend_exit_confirm_bars or 3)))
    recent = range(len(closes) - confirm_bars, len(closes))
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) else 0.0
    vol_ratio = float(volumes[-1] / vol_avg) if vol_avg > 0 else 1.0
    if sim.side == PositionSide.LONG:
        macd_turn = hist[-1] < hist[-2] < hist[-3] and hist[-1] < 0
        candle_break = all(closes[i] < ema20[i] for i in recent) and closes[-1] < opens[-1]
    else:
        macd_turn = hist[-1] > hist[-2] > hist[-3] and hist[-1] > 0
        candle_break = all(closes[i] > ema20[i] for i in recent) and closes[-1] > opens[-1]
    reversal_ok = (
        (macd_turn and candle_break)
        or (macd_turn and vol_ratio >= 1.05)
        or (candle_break and vol_ratio >= 1.1)
    )
    if pos.unrealized_pnl > 0 and reversal_ok:
        return True, f"추세 이탈 ({confirm_bars}캔들 확인)"
    return False, ""


def _trend_scale_signal_bt(
    sim: _SimPos,
    candles: list[list],
    idx: int,
    cfg: AppConfig,
) -> tuple[bool, str]:
    if not cfg.trend_scale_in or sim.scale_in_count >= cfg.max_scale_ins:
        return False, ""
    window = candles[: idx + 1]
    if len(window) < 55:
        return False, ""
    opens = np.array([float(c[1]) for c in window])
    highs = np.array([float(c[2]) for c in window])
    lows = np.array([float(c[3]) for c in window])
    closes = np.array([float(c[4]) for c in window])
    volumes = np.array([float(c[5]) for c in window])
    pos = _to_position(sim, float(closes[-1]), cfg)
    if pos.unrealized_pnl_pct < cfg.scale_in_min_pnl_pct:
        return False, ""
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    hist = _macd_hist(closes)
    if len(hist) < 4:
        return False, ""
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) else 0.0
    vol_ratio = float(volumes[-1] / vol_avg) if vol_avg > 0 else 1.0
    candle_range = max(float(highs[-1] - lows[-1]), float(closes[-1]) * 0.0001)
    strong_body = abs(float(closes[-1] - opens[-1])) / candle_range >= 0.45
    last_scale = sim.last_scale_price or sim.entry_price
    if sim.side == PositionSide.LONG:
        trend_ok = closes[-1] > ema20[-1] > ema50[-1] and ema20[-1] > ema20[-4]
        macd_ok = hist[-1] > 0 and hist[-1] > hist[-2] > hist[-3]
        candle_ok = closes[-1] > opens[-1] and closes[-1] >= highs[-1] - candle_range * 0.25
        spacing_ok = closes[-1] >= last_scale * 1.004
    else:
        trend_ok = closes[-1] < ema20[-1] < ema50[-1] and ema20[-1] < ema20[-4]
        macd_ok = hist[-1] < 0 and hist[-1] < hist[-2] < hist[-3]
        candle_ok = closes[-1] < opens[-1] and closes[-1] <= lows[-1] + candle_range * 0.25
        spacing_ok = closes[-1] <= last_scale * 0.996
    ok = trend_ok and macd_ok and candle_ok and strong_body and vol_ratio >= 1.5 and spacing_ok
    return ok, f"추가진입 조건 (거래량 {vol_ratio:.1f}배)"


def simulate_symbol(
    inst_id: str,
    candles: list[list],
    config: AppConfig,
    state: _SimState,
    logs: list[BacktestLogEntry],
    min_score_override: float | None = None,
    invert_signals: bool = False,
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
            trend_exit, trend_reason = _trend_break_signal_bt(sim, candles, i, cfg)
            if trend_exit:
                _record_close(sim, inst_id, price, i, state, logs, trend_reason, cfg.leverage)
                del state.positions[iid]
                continue
            exit_flag, reason = should_exit(pos, cfg)
            if exit_flag:
                _record_close(sim, inst_id, price, i, state, logs, reason, cfg.leverage)
                del state.positions[iid]

        if inst_id in state.positions:
            sim = state.positions[inst_id]
            if sim.side == PositionSide.LONG:
                sim.trailing_high = max(sim.trailing_high, price)
            else:
                sim.trailing_high = min(sim.trailing_high, price) if sim.trailing_high > 0 else price
            scale_ok, scale_reason = _trend_scale_signal_bt(sim, candles, i, cfg)
            if scale_ok:
                snap = _portfolio_snap(state)
                base_notional = resolve_order_size_usdt(cfg, snap, open_positions=len(state.positions))
                add_notional = base_notional * max(5.0, min(100.0, cfg.scale_in_size_pct)) / 100
                if add_notional > 0:
                    add_qty = add_notional / price if price > 0 else 0
                    old_qty = sim.quantity
                    new_qty = old_qty + add_qty
                    if new_qty > 0:
                        sim.entry_price = ((sim.entry_price * old_qty) + (price * add_qty)) / new_qty
                        sim.quantity = new_qty
                        sim.notional += add_notional
                        sim.scale_in_count += 1
                        sim.last_scale_price = price
                        sim.stop_loss, sim.take_profit = _sl_tp_prices(
                            sim.entry_price,
                            sim.side,
                            sim.sl_pct,
                            sim.tp_pct,
                            cfg.leverage,
                        )
                        logs.append(
                            BacktestLogEntry(
                                ts=_utc_now(),
                                level="info",
                                message=(
                                    f"{inst_id} 백테스트 추가진입 #{sim.scale_in_count} "
                                    f"bar={i} 명목 ${add_notional:,.0f} · {scale_reason}"
                                ),
                            )
                        )
            continue

        if len(state.positions) >= cfg.max_positions:
            continue

        for strat in strat_list:
            cand = _build_candidate(inst_id, closes, volumes, i, strat)
            side = resolve_entry_side(cfg, cand)
            if invert_signals:
                side = _flip_side(side)
            if side is None:
                continue
            snap = _portfolio_snap(state)
            ok, msg = check_entry_allowed(cfg, snap, cand, strat, entry_side=side)
            if not ok:
                continue

            sl_pct, tp_pct = sl_tp_pcts(cfg, strat)
            sl, tp = _sl_tp_prices(price, side, sl_pct, tp_pct, cfg.leverage)
            notional = resolve_order_size_usdt(cfg, snap, open_positions=len(state.positions))
            lev = max(1, cfg.leverage)
            margin = notional / lev
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
                last_scale_price=price,
            )
            logs.append(
                BacktestLogEntry(
                    ts=_utc_now(),
                    level="info",
                    message=(
                        f"{inst_id} 진입 {side.value} bar={i} score={cand.score:.0f} "
                        f"명목 ${notional:,.0f} · 증거금 ${margin:,.0f} ({lev}x) "
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
    invert_signals: bool = False,
    window_ratio: float = 1.0,
) -> tuple[_SimState, int]:
    state = _SimState(equity=config.paper_initial_balance or settings.initial_balance)
    total_bars = 0
    sliced: dict[str, list[list]] = {
        iid: _slice_candles(c, window_ratio) for iid, c in symbol_candles.items()
    }
    for inst_id, candles in sliced.items():
        logs.append(
            BacktestLogEntry(
                ts=_utc_now(),
                level="info",
                message=f"--- {inst_id} 시뮬레이션 (봉 {len(candles)}, {'역방향' if invert_signals else '정방향'}) ---",
            )
        )
        total_bars += simulate_symbol(
            inst_id,
            candles,
            config,
            state,
            logs,
            min_score_override,
            invert_signals=invert_signals,
        )

    _close_open_positions(sliced, state, logs, config.leverage)
    return state, total_bars


def _metrics_from_state(
    state: _SimState,
    bars: int,
    start_equity: float,
    order_notional: float = 0.0,
) -> BacktestMetrics:
    trades = state.trades
    wins = sum(1 for t in trades if t.pnl_usdt > 0)
    total_pnl = sum(t.pnl_usdt for t in trades)
    total_fees = sum(t.fee_usdt for t in trades)
    if not order_notional and trades:
        order_notional = sum(t.notional_usdt for t in trades) / len(trades)
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
        start_equity=round(start_equity, 2),
        end_equity=round(state.equity, 2),
        order_notional_usdt=round(order_notional, 2),
        total_fees_usdt=round(total_fees, 2),
    )


def _trial_rank(pnl: float, win_rate: float, trades: int) -> float:
    if trades < 1:
        return -1e9
    if trades < 3:
        return pnl - 25 + trades * 2
    expectancy = pnl / trades
    trade_bonus = min(trades, 40) * 0.45
    sparse_penalty = max(0, 8 - trades) * 3.0
    return pnl * 1.1 + expectancy * 8.0 + win_rate * 0.12 + trade_bonus - sparse_penalty


def _sl_tp_rank(
    win_rate: float,
    pnl: float,
    trades: int,
    tp_hits: int,
    tp_pct: float,
    strategy: StrategyMode,
) -> float:
    """
    승률 우선으로 랭킹을 매기되, TP가 전략 상한을 넘으면 페널티를 적용한다.
    - 승률이 높아도 TP를 무조건 높이는 방향을 막기 위해
      전략별 TP 상한(TP_MAX_BY_STRATEGY) 초과 시 페널티 부여
    - 적정 TP 범위 안에서 승률+PnL+tp_hits를 최대화하는 조합 선택
    """
    if trades < 2:
        return -1e9

    tp_max = TP_MAX_BY_STRATEGY.get(strategy, 14.0)

    # TP 상한 초과 시 페널티 (초과량에 비례)
    tp_penalty = 0.0
    if tp_pct > tp_max:
        tp_penalty = (tp_pct - tp_max) * 5.0  # 1%당 5점 페널티

    # 승률이 60% 이상일 때는 TP를 낮추는 방향을 선호 (빠른 익절이 더 유리)
    tp_size_penalty = 0.0
    if win_rate >= 60 and tp_pct > tp_max * 0.75:
        tp_size_penalty = (tp_pct - tp_max * 0.75) * 2.0

    tp_bonus = min(tp_hits, trades) * 0.4
    base = win_rate * 3.5 + min(trades, 30) * 0.2 + pnl * 0.08 + tp_bonus
    return base - tp_penalty - tp_size_penalty


def _sl_tp_rank(
    win_rate: float,
    pnl: float,
    trades: int,
    tp_hits: int,
    tp_pct: float,
    strategy: StrategyMode,
) -> float:
    """Rank SL/TP by expectancy, TP hit rate, and enough trade samples."""
    if trades < 2:
        return -1e9

    tp_max = TP_MAX_BY_STRATEGY.get(strategy, 14.0)
    tp_rate = tp_hits / trades if trades > 0 else 0.0
    unresolved = max(0, trades - tp_hits)
    expectancy = pnl / trades if trades > 0 else -999.0

    tp_penalty = 0.0
    if tp_pct > tp_max:
        tp_penalty += (tp_pct - tp_max) * 10.0
    if strategy == StrategyMode.SCALP and tp_pct > 8.0:
        tp_penalty += (tp_pct - 8.0) * 2.5

    sparse_penalty = max(0, 6 - trades) * 8.0
    low_tp_hit_penalty = max(0.0, 0.28 - tp_rate) * 45.0
    unresolved_penalty = (unresolved / trades) * 10.0 if trades else 0.0
    tp_hit_bonus = tp_rate * 28.0 + min(tp_hits, 20) * 0.6
    base = pnl * 1.25 + expectancy * 14.0 + win_rate * 0.18 + min(trades, 45) * 0.45 + tp_hit_bonus
    return base - tp_penalty - sparse_penalty - low_tp_hit_penalty - unresolved_penalty


def _count_exit_types(trades: list[BacktestTrade]) -> tuple[int, int]:
    sl_hits = tp_hits = 0
    for t in trades:
        if "손절" in t.exit_reason:
            sl_hits += 1
        elif "익절" in t.exit_reason:
            tp_hits += 1
    return sl_hits, tp_hits


def optimize_sl_tp(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
    min_score: float,
    invert_signals: bool,
    window_ratio: float,
) -> tuple[float, float, list[BacktestSlTpTrial], str]:
    trials: list[BacktestSlTpTrial] = []
    best_rank = float("-inf")
    best_sl = config.stop_loss_pct or 2.0
    best_tp = config.take_profit_pct or 3.0
    base_sl = best_sl
    base_tp = best_tp

    # 전략별 TP 상한 적용
    strategy = config.strategy_mode
    tp_max = TP_MAX_BY_STRATEGY.get(strategy, 14.0)

    sl_candidates = sorted(set(SL_GRID + [round(base_sl * 0.75, 2), round(base_sl, 2), round(base_sl * 1.25, 2)]))
    # TP 후보를 전략 상한으로 제한
    tp_candidates = sorted(set(
        [t for t in TP_GRID if t <= tp_max]
        + [round(base_tp * 0.75, 2), round(min(base_tp, tp_max), 2), round(min(base_tp * 1.25, tp_max), 2)]
    ))

    logs.append(
        BacktestLogEntry(
            ts=_utc_now(),
            level="info",
            message=(
                f"SL/TP 탐색 (승률 우선, TP상한 {tp_max}%) — "
                f"score={min_score} SL 후보 {len(sl_candidates)} × TP {len(tp_candidates)}"
            ),
        )
    )

    for sl in sl_candidates:
        for tp in tp_candidates:
            # SL 대비 최소 1.5배 이상 TP (기존 2.0배에서 완화 — 단타는 1.5배도 충분)
            min_ratio = 1.15 if strategy == StrategyMode.SCALP else 1.5
            max_ratio = 1.8 if strategy == StrategyMode.SCALP else 2.4
            if tp < sl * min_ratio:
                continue
            if tp > sl * max_ratio:
                continue
            cfg = config.model_copy(deep=True)
            cfg.stop_loss_pct = sl
            cfg.take_profit_pct = tp
            state, _ = run_simulation(
                cfg,
                symbol_candles,
                [],
                min_score_override=min_score,
                invert_signals=invert_signals,
                window_ratio=window_ratio,
            )
            pnl = sum(t.pnl_usdt for t in state.trades)
            wins = sum(1 for t in state.trades if t.pnl_usdt > 0)
            wr = wins / len(state.trades) * 100 if state.trades else 0.0
            sl_h, tp_h = _count_exit_types(state.trades)
            trial = BacktestSlTpTrial(
                stop_loss_pct=sl,
                take_profit_pct=tp,
                total_pnl=round(pnl, 2),
                win_rate=round(wr, 1),
                trades=len(state.trades),
                tp_hits=tp_h,
                sl_hits=sl_h,
            )
            trials.append(trial)
            rank = _sl_tp_rank(wr, pnl, len(state.trades), tp_h, tp, strategy)
            if rank > best_rank:
                best_rank = rank
                best_sl, best_tp = sl, tp

    reason = (
        f"승률 우선 SL {best_sl}% / TP {best_tp}% "
        f"(TP상한 {tp_max}%, 후보 {len(trials)}개, score={min_score})"
    )
    reason = (
        f"기대값/TP도달률 우선 SL {best_sl}% / TP {best_tp}% "
        f"(TP상한 {tp_max}%, 후보 {len(trials)}개, score={min_score})"
    )
    top = sorted(
        trials,
        key=lambda t: _sl_tp_rank(t.win_rate, t.total_pnl, t.trades, t.tp_hits, t.take_profit_pct, strategy),
        reverse=True,
    )
    if top:
        t0 = top[0]
        reason += f" — 최고 승률 {t0.win_rate}% PnL {t0.total_pnl:+.2f} ({t0.trades}건)"
    if top:
        t0 = top[0]
        reason = (
            f"SL/TP rank by expectancy and TP-hit: SL {best_sl}% / TP {best_tp}% "
            f"(cap {tp_max}%, candidates {len(trials)}, score={min_score}) — "
            f"top win {t0.win_rate}% PnL {t0.total_pnl:+.2f} TP hits {t0.tp_hits}/{t0.trades}"
        )
    return best_sl, best_tp, trials, reason


def optimize_strategy(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
) -> BacktestRecommendation:
    direction_trials: list[BacktestDirectionTrial] = []
    score_trials: list[BacktestScoreTrial] = []
    best_rank = float("-inf")
    best: BacktestDirectionTrial | None = None

    logs.append(
        BacktestLogEntry(
            ts=_utc_now(),
            level="info",
            message="전략 탐색: 정방향/역방향 × 구간(100/75/50%) × min_score",
        )
    )

    mode_settings = (
        ("normal", False, config.position_side),
        ("long_only", False, PositionSideMode.LONG),
        ("short_only", False, PositionSideMode.SHORT),
        ("inverse", True, config.position_side),
    )
    for mode, invert, side_mode in mode_settings:
        for wratio in WINDOW_RATIOS:
            for ms in SCORE_GRID:
                trial_logs: list[BacktestLogEntry] = []
                trial_cfg = config.model_copy(deep=True)
                trial_cfg.position_side = side_mode
                state, _ = run_simulation(
                    trial_cfg,
                    symbol_candles,
                    trial_logs,
                    min_score_override=ms,
                    invert_signals=invert,
                    window_ratio=wratio,
                )
                pnl = sum(t.pnl_usdt for t in state.trades)
                wins = sum(1 for t in state.trades if t.pnl_usdt > 0)
                win_r = wins / len(state.trades) * 100 if state.trades else 0.0
                long_n = sum(1 for t in state.trades if t.side == "long")
                short_n = sum(1 for t in state.trades if t.side == "short")
                dt = BacktestDirectionTrial(
                    mode=mode,
                    window_ratio=wratio,
                    min_score=ms,
                    total_pnl=round(pnl, 2),
                    win_rate=round(win_r, 1),
                    trades=len(state.trades),
                    long_trades=long_n,
                    short_trades=short_n,
                )
                direction_trials.append(dt)
                rank = _trial_rank(pnl, win_r, len(state.trades))
                if rank > best_rank:
                    best_rank = rank
                    best = dt

    if best is None:
        best = BacktestDirectionTrial(
            mode="normal",
            window_ratio=1.0,
            min_score=config.min_score,
            total_pnl=0,
            win_rate=0,
            trades=0,
        )

    for ms in SCORE_GRID:
        st_logs: list[BacktestLogEntry] = []
        best_cfg = _config_for_direction(config, best.mode)
        st, _ = run_simulation(
            best_cfg,
            symbol_candles,
            st_logs,
            min_score_override=ms,
            invert_signals=best.mode == "inverse",
            window_ratio=best.window_ratio,
        )
        pnl = sum(t.pnl_usdt for t in st.trades)
        wins = sum(1 for t in st.trades if t.pnl_usdt > 0)
        wr = wins / len(st.trades) * 100 if st.trades else 0
        score_trials.append(
            BacktestScoreTrial(
                min_score=ms,
                total_pnl=round(pnl, 2),
                win_rate=round(wr, 1),
                trades=len(st.trades),
                long_entries=sum(1 for t in st.trades if t.side == "long"),
                short_entries=sum(1 for t in st.trades if t.side == "short"),
            )
        )

    long_best = max(
        (t for t in direction_trials if t.mode in ("normal", "long_only") and (t.long_trades or 0) > 0),
        key=lambda t: _trial_rank(t.total_pnl, t.win_rate, t.trades),
        default=None,
    )
    short_best = max(
        (t for t in direction_trials if t.mode in ("short_only", "inverse") and (t.short_trades or 0) > 0),
        key=lambda t: _trial_rank(t.total_pnl, t.win_rate, t.trades),
        default=None,
    )

    dir_reason = (
        f"최적 {best.mode} 구간 {int(best.window_ratio * 100)}% "
        f"min_score={best.min_score} PnL {best.total_pnl:+.2f} 승률 {best.win_rate}%"
    )
    if (
        long_best
        and short_best
        and long_best.win_rate < 45
        and short_best.win_rate >= long_best.win_rate + 8
    ):
        dir_reason += (
            f" | 롱 승률 {long_best.win_rate}% 낮음 -> 숏/반전 {short_best.win_rate}% 우세"
        )

    rec_sl, rec_tp, sl_tp_trials, sl_tp_reason = optimize_sl_tp(
        _config_for_direction(config, best.mode),
        symbol_candles,
        logs,
        best.min_score,
        best.mode == "inverse",
        best.window_ratio,
    )

    return BacktestRecommendation(
        min_score=best.min_score,
        reason=dir_reason,
        trials=score_trials,
        direction=best.mode,
        direction_reason=dir_reason,
        direction_trials=direction_trials,
        window_ratio=best.window_ratio,
        stop_loss_pct=rec_sl,
        take_profit_pct=rec_tp,
        sl_tp_reason=sl_tp_reason,
        sl_tp_trials=sl_tp_trials,
    )


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
        recommendation = optimize_strategy(config, symbol_candles, logs)
        logs.append(
            BacktestLogEntry(
                ts=_utc_now(),
                level="ok",
                message=(
                    f"추천 {recommendation.direction} / min_score={recommendation.min_score} "
                    f"/ 구간 {int(recommendation.window_ratio * 100)}% — {recommendation.reason}"
                ),
            )
        )

    invert_run = recommendation.direction == "inverse" if recommendation else False
    window_run = recommendation.window_ratio if recommendation else 1.0
    min_run = recommendation.min_score if recommendation else config.min_score

    run_cfg = config.model_copy(deep=True)
    if recommendation:
        run_cfg = _config_for_direction(run_cfg, recommendation.direction)
    if recommendation and recommendation.stop_loss_pct > 0 and recommendation.take_profit_pct > 0:
        run_cfg.stop_loss_pct = recommendation.stop_loss_pct
        run_cfg.take_profit_pct = recommendation.take_profit_pct

    state, bars = run_simulation(
        run_cfg,
        symbol_candles,
        logs,
        min_score_override=min_run,
        invert_signals=invert_run,
        window_ratio=window_run,
    )
    initial_snap = PortfolioSnapshot(
        balance=start_equity,
        equity=start_equity,
        available=start_equity,
        unrealized_pnl=0,
        realized_pnl=0,
        positions=[],
        trade_count=0,
        win_rate=0,
    )
    order_notional = resolve_order_size_usdt(run_cfg, initial_snap, open_positions=0)
    metrics = _metrics_from_state(state, bars, start_equity, order_notional)

    finished = _utc_now()
    logs.append(
        BacktestLogEntry(
            ts=finished,
            level="ok",
            message=(
                f"완료 시작 ${metrics.start_equity:,.0f} → 최종 ${metrics.end_equity:,.0f} "
                f"(손익 {metrics.total_pnl:+.2f} USDT, {metrics.total_pnl_pct:+.2f}%) "
                f"1회 명목 ${metrics.order_notional_usdt:,.0f} · "
                f"거래 {metrics.trade_count}건 승률 {metrics.win_rate}%"
            ),
        )
    )

    candle_bars = max((len(c) for c in symbol_candles.values()), default=0)
    strat_list = active_strategies(config)
    if StrategyMode.SWING in strat_list and StrategyMode.SCALP not in strat_list:
        interval = "1H"
    elif StrategyMode.SCALP in strat_list and StrategyMode.SWING in strat_list:
        interval = "5m/1H"
    else:
        interval = "5m"
    charts = build_symbol_charts(symbol_candles, state.trades)
    zone_walkforward = evaluate_zone_walkforward(symbol_candles)
    logs.append(
        BacktestLogEntry(
            ts=_utc_now(),
            level="info",
            message=(
                f"구간 워크포워드: {zone_walkforward.samples}개 예측, "
                f"정확도 {zone_walkforward.accuracy_pct}% "
                f"(롱 {zone_walkforward.long_accuracy_pct}% / 숏 {zone_walkforward.short_accuracy_pct}%), "
                f"평균 {zone_walkforward.avg_forward_r}R, 실패돌파 {zone_walkforward.false_break_pct}%"
            ),
        )
    )

    symbol_profile_data: dict[str, dict] = {}
    if recommendation and symbol_candles:
        from app.backtest.symbol_sl_tp import build_symbol_profiles, persist_profiles_from_backtest

        built = build_symbol_profiles(
            run_cfg,
            symbol_candles,
            state.trades,
            min_run,
            invert_run,
            window_run,
            rid,
        )
        if built:
            merged = persist_profiles_from_backtest(built)
            symbol_profile_data = {k: v.model_dump() for k, v in merged.items()}
            for iid, p in built.items():
                logs.append(
                    BacktestLogEntry(
                        ts=_utc_now(),
                        level="info",
                        message=(
                            f"{iid} 종목 SL/TP — SL {p.stop_loss_pct}% TP {p.take_profit_pct}% "
                            f"승률 {p.win_rate}% ({p.trades}건"
                            f"{f'·익절평균 {p.avg_win_tp_pct}%' if p.avg_win_tp_pct else ''})"
                        ),
                    )
                )

    return BacktestResult(
        id=rid,
        status="done",
        started_at=started,
        finished_at=finished,
        strategy_mode=config.strategy_mode.value,
        symbols=symbols,
        candle_bars=candle_bars,
        candle_interval=interval,
        symbol_charts=charts,
        params_snapshot={
            "min_score": config.min_score,
            "min_score_applied": min_run,
            "direction": recommendation.direction if recommendation else "normal",
            "window_ratio": window_run,
            "invert_signals": invert_run,
            "max_positions": config.max_positions,
            "order_size_usdt": config.order_size_usdt,
            "position_side": config.position_side.value,
            "leverage": config.leverage,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "stop_loss_pct_applied": run_cfg.stop_loss_pct,
            "take_profit_pct_applied": run_cfg.take_profit_pct,
            "trend_scale_in": run_cfg.trend_scale_in,
            "max_scale_ins": run_cfg.max_scale_ins,
            "scale_in_size_pct": run_cfg.scale_in_size_pct,
            "scale_in_min_pnl_pct": run_cfg.scale_in_min_pnl_pct,
            "trend_exit_confirm_bars": run_cfg.trend_exit_confirm_bars,
            "start_equity": start_equity,
            "end_equity": metrics.end_equity,
            "order_notional_usdt": metrics.order_notional_usdt,
        },
        metrics=metrics,
        recommendation=recommendation,
        trades=state.trades,
        logs=logs,
        symbol_profiles=symbol_profile_data,
        zone_walkforward=zone_walkforward,
    )
