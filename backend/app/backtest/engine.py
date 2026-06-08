"""Historical bar-by-bar backtest aligned with live entry/exit rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

from app.candle_patterns import backtest_three_soldiers_signal
from app.config import settings
from app.entry_signals import resolve_entry_side
from app.engine.exit_rules import should_exit
from app.engine.risk_manager import check_entry_allowed
from app.market.entry_analyzer import _analyze_closes
from app.market.technical_indicators import indicator_snapshot
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
    BacktestProfitProtectTrial,
    BacktestRecommendation,
    BacktestResult,
    BacktestScoreTrial,
    BacktestSlTpTrial,
    BacktestTrade,
)

SCORE_GRID = [45.0, 50.0, 55.0, 60.0, 65.0, 70.0]
WINDOW_RATIOS = [1.0, 0.75, 0.5]

# symbol_sl_tp.py 호환용 — optimize_symbol_sl_tp에서 보조 후보로 사용
SL_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
TP_GRID = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 15.0, 18.0]

# TP 전략별 상한 (이 이상이면 백테스트 추천에서 패널티)
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
    profit_protect_armed_at: float = 0.0
    profit_protect_floor_pct: float = 0.0


@dataclass
class _SimState:
    equity: float
    positions: dict[str, _SimPos] = field(default_factory=dict)
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


def _candles_to_arrays(candles: list[list]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    highs = np.array([float(c[2]) for c in candles])
    lows = np.array([float(c[3]) for c in candles])
    closes = np.array([float(c[4]) for c in candles])
    volumes = np.array([float(c[5]) for c in candles])
    return highs, lows, closes, volumes


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
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    idx: int,
    strategy: StrategyMode,
) -> CoinCandidate:
    window_h = highs[: idx + 1]
    window_l = lows[: idx + 1]
    window_c = closes[: idx + 1]
    window_v = volumes[: idx + 1]
    score, scalp_ok, swing_ok, outlook, reasons, rsi, trend, short_scalp, short_swing = (
        _analyze_closes(window_c, window_v, strategy, window_h, window_l)
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
            message=f"{inst_id} 청산 {reason} | 금액 ${sim.notional:,.0f} 손익 {pnl:+.2f} USDT ({pnl_pct:+.2f}%)",
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


def _to_position(sim: _SimPos, price: float, config: AppConfig, bar_i: int = 0) -> Position:
    cost = sim.entry_price * sim.quantity if sim.quantity else sim.notional
    if sim.side == PositionSide.LONG:
        upnl = (price - sim.entry_price) * sim.quantity
    else:
        upnl = (sim.entry_price - price) * sim.quantity
    margin = cost / max(1, config.leverage) if config.instrument_type != InstrumentType.SPOT else cost
    upnl_pct = upnl / margin * 100 if margin > 0 else 0
    return Position(
        id=f"bt:{bar_i}",
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
        profit_protect_armed_at=sim.profit_protect_armed_at,
        profit_protect_floor_pct=sim.profit_protect_floor_pct,
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
        return True, f"추세 반전 ({confirm_bars}봉 확인)"
    return False, ""


def _advanced_exit_signal_bt(
    sim: _SimPos,
    candles: list[list],
    idx: int,
    cfg: AppConfig,
) -> tuple[bool, str]:
    if idx < 35:
        return False, ""
    window = candles[: idx + 1]
    if len(window) < 35:
        return False, ""
    try:
        highs = [float(c[2]) for c in window[-90:]]
        lows = [float(c[3]) for c in window[-90:]]
        closes = [float(c[4]) for c in window[-90:]]
        volumes = [float(c[5]) if len(c) > 5 else 0.0 for c in window[-90:]]
    except (TypeError, ValueError, IndexError):
        return False, ""
    snap = indicator_snapshot(highs, lows, closes, volumes)
    if not snap:
        return False, ""
    pos = _to_position(sim, float(closes[-1]), cfg)
    st_dir = int(snap.get("supertrend_direction", 0))
    st_line = float(snap.get("supertrend_line", 0.0))
    stoch_k = float(snap.get("stoch_k", 50.0))
    stoch_d = float(snap.get("stoch_d", 50.0))
    adx_val = float(snap.get("adx", 20.0))
    vol_ratio = float(snap.get("vol_ratio", 1.0))
    current = float(closes[-1])

    if sim.side == PositionSide.LONG and st_dir == -1 and current < st_line:
        return True, f"Supertrend 하향 전환 (ADX {adx_val:.0f})"
    if sim.side == PositionSide.SHORT and st_dir == 1 and current > st_line:
        return True, f"Supertrend 상향 전환 (ADX {adx_val:.0f})"
    if pos.unrealized_pnl <= 0:
        return False, ""
    if sim.side == PositionSide.LONG and stoch_k < stoch_d and stoch_k >= 70:
        return True, f"익절 신호: Stoch 과매수 하락 {stoch_k:.0f}"
    if sim.side == PositionSide.SHORT and stoch_k > stoch_d and stoch_k <= 30:
        return True, f"익절 신호: Stoch 과매도 반등 {stoch_k:.0f}"
    if adx_val < 18 and vol_ratio < 0.8:
        return True, f"익절 신호: ADX/거래량 약화 ({adx_val:.0f}, {vol_ratio:.1f}배)"
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
    return ok, f"추세추종 추가진입 (거래량 {vol_ratio:.1f}배)"


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

    highs, lows, closes, volumes = _candles_to_arrays(candles)
    cfg = config.model_copy(deep=True)
    if min_score_override is not None:
        cfg.min_score = min_score_override

    strat_list = active_strategies(cfg)
    if not strat_list:
        strat_list = [StrategyMode.SCALP]
    base_interval = "1H" if StrategyMode.SWING in strat_list and StrategyMode.SCALP not in strat_list else "5m"

    bar_count = 0
    for i in range(60, len(closes)):
        price = float(closes[i])
        bar_count += 1

        for iid in list(state.positions.keys()):
            if iid != inst_id:
                continue
            sim = state.positions[iid]
            pos = _to_position(sim, price, cfg, i)
            exit_flag, reason = should_exit(pos, cfg)
            sim.profit_protect_armed_at = pos.profit_protect_armed_at
            sim.profit_protect_floor_pct = pos.profit_protect_floor_pct
            if exit_flag:
                _record_close(sim, inst_id, price, i, state, logs, reason, cfg.leverage)
                del state.positions[iid]
                continue
            if pos.unrealized_pnl > 0:
                continue
            trend_exit, trend_reason = _trend_break_signal_bt(sim, candles, i, cfg)
            if trend_exit:
                _record_close(sim, inst_id, price, i, state, logs, trend_reason, cfg.leverage)
                del state.positions[iid]
                continue
            advanced_exit, advanced_reason = _advanced_exit_signal_bt(sim, candles, i, cfg)
            if advanced_exit:
                _record_close(sim, inst_id, price, i, state, logs, advanced_reason, cfg.leverage)
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
                            sim.entry_price, sim.side, sim.sl_pct, sim.tp_pct, cfg.leverage,
                        )
                        logs.append(BacktestLogEntry(
                            ts=_utc_now(), level="info",
                            message=f"{inst_id} 추가진입 #{sim.scale_in_count} bar={i} ${add_notional:,.0f} · {scale_reason}",
                        ))
            continue

        if len(state.positions) >= cfg.max_positions:
            continue

        for strat in strat_list:
            cand = _build_candidate(inst_id, highs, lows, closes, volumes, i, strat)
            three_pattern = backtest_three_soldiers_signal(
                candles, i, base_interval, cfg.leverage, cfg.instrument_type,
            )
            if three_pattern:
                cand.score = round(cand.score + three_pattern.score_bonus, 1)
                cand.reasons.append(three_pattern.reason)
                if three_pattern.side == PositionSide.LONG:
                    cand.outlook = "long"
                    cand.trend = "up" if cand.trend != "strong_up" else cand.trend
                    if three_pattern.interval == "1H":
                        cand.swing_ok = True
                    elif three_pattern.interval == "10m":
                        cand.scalp_ok = True
                        cand.swing_ok = cand.swing_ok or cand.score >= 55
                    else:
                        cand.scalp_ok = cand.scalp_ok or cand.score >= 55
                else:
                    cand.outlook = "short"
                    cand.trend = "down"
                    cand.short_scalp_ok = True
                    cand.short_swing_ok = three_pattern.interval == "1H" or cand.score >= 55
            side = resolve_entry_side(cfg, cand)
            if invert_signals:
                side = _flip_side(side)
            if side is None:
                continue
            snap = _portfolio_snap(state)
            ok, msg = check_entry_allowed(cfg, snap, cand, strat, entry_side=side)
            if not ok:
                continue

            if three_pattern and side == three_pattern.side and not invert_signals:
                sl_pct, tp_pct = three_pattern.sl_pct, three_pattern.tp_pct
                sl, tp = three_pattern.stop_loss, three_pattern.take_profit
            else:
                sl_pct, tp_pct = sl_tp_pcts(cfg, strat)
                sl, tp = _sl_tp_prices(price, side, sl_pct, tp_pct, cfg.leverage)
            notional = resolve_order_size_usdt(cfg, snap, open_positions=len(state.positions))
            lev = max(1, cfg.leverage)
            margin = notional / lev
            state.positions[inst_id] = _SimPos(
                inst_id=inst_id, side=side, strategy=strat,
                entry_bar=i, entry_price=price,
                quantity=notional / price if price > 0 else 0,
                notional=notional, stop_loss=sl, take_profit=tp,
                sl_pct=sl_pct, tp_pct=tp_pct, trailing_high=price,
                score=cand.score, last_scale_price=price,
            )
            logs.append(BacktestLogEntry(
                ts=_utc_now(), level="info",
                message=(
                    f"{inst_id} 진입 {side.value} bar={i} score={cand.score:.0f} "
                    f"${notional:,.0f} · 증거금 ${margin:,.0f} ({lev}x) SL{sl_pct}% TP{tp_pct}%"
                    + (f" · {three_pattern.reason}" if three_pattern and side == three_pattern.side else "")
                ),
            ))
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
        direction_label = "역방향" if invert_signals else "정방향"
        logs.append(BacktestLogEntry(
            ts=_utc_now(), level="info",
            message=f"--- {inst_id} 시뮬레이션 (캔들 {len(candles)}, {direction_label}) ---",
        ))
        total_bars += simulate_symbol(
            inst_id, candles, config, state, logs, min_score_override, invert_signals=invert_signals,
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
    if trades < 2:
        return -1e9
    tp_max = TP_MAX_BY_STRATEGY.get(strategy, 14.0)
    tp_rate = tp_hits / trades if trades > 0 else 0.0
    unresolved = max(0, trades - tp_hits)
    expectancy = pnl / trades if trades > 0 else -999.0

    tp_penalty = 0.0
    if tp_pct > tp_max:
        tp_penalty += (tp_pct - tp_max) * 10.0

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


def _count_profit_protect_hits(trades: list[BacktestTrade]) -> int:
    return sum(1 for t in trades if "수익 보호" in t.exit_reason or "이익 보호" in t.exit_reason)


def optimize_sl_tp(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
    min_score: float,
    invert_signals: bool,
    window_ratio: float,
) -> tuple[float, float, list[BacktestSlTpTrial], str]:
    base_sl = float(config.stop_loss_pct) if config.stop_loss_pct else 3.0
    base_tp = float(config.take_profit_pct) if config.take_profit_pct else 5.0
    strategy = config.strategy_mode
    tp_max = TP_MAX_BY_STRATEGY.get(strategy, 14.0)

    sl_candidates = sorted(set([
        round(max(0.5, base_sl * 0.5), 2),
        round(max(0.5, base_sl * 0.7), 2),
        round(max(0.5, base_sl * 0.85), 2),
        round(max(0.5, base_sl), 2),
        round(max(0.5, base_sl * 1.2), 2),
        round(max(0.5, base_sl * 1.5), 2),
        round(max(0.5, base_sl * 2.0), 2),
    ]))

    tp_candidates = sorted(set([
        round(min(tp_max, max(base_tp * 0.6, base_sl * 1.1)), 2),
        round(min(tp_max, max(base_tp * 0.8, base_sl * 1.1)), 2),
        round(min(tp_max, max(base_tp, base_sl * 1.1)), 2),
        round(min(tp_max, max(base_tp * 1.2, base_sl * 1.1)), 2),
        round(min(tp_max, max(base_tp * 1.5, base_sl * 1.1)), 2),
        round(min(tp_max, max(base_tp * 2.0, base_sl * 1.1)), 2),
    ]))

    logs.append(BacktestLogEntry(
        ts=_utc_now(), level="info",
        message=(
            f"SL/TP 탐색 (설정값 기준: SL {base_sl}% / TP {base_tp}%, TP상한 {tp_max}%) "
            f"score={min_score} SL후보 {len(sl_candidates)}개 TP {len(tp_candidates)}개"
        ),
    ))

    trials: list[BacktestSlTpTrial] = []
    best_rank = float("-inf")
    best_sl = base_sl
    best_tp = base_tp

    for sl in sl_candidates:
        for tp in tp_candidates:
            if tp < sl * 1.1:
                continue
            cfg = config.model_copy(deep=True)
            cfg.stop_loss_pct = sl
            cfg.take_profit_pct = tp
            state, _ = run_simulation(
                cfg, symbol_candles, [],
                min_score_override=min_score,
                invert_signals=invert_signals,
                window_ratio=window_ratio,
            )
            pnl = sum(t.pnl_usdt for t in state.trades)
            wins = sum(1 for t in state.trades if t.pnl_usdt > 0)
            wr = wins / len(state.trades) * 100 if state.trades else 0.0
            sl_h, tp_h = _count_exit_types(state.trades)
            trial = BacktestSlTpTrial(
                stop_loss_pct=sl, take_profit_pct=tp,
                total_pnl=round(pnl, 2), win_rate=round(wr, 1),
                trades=len(state.trades), tp_hits=tp_h, sl_hits=sl_h,
            )
            trials.append(trial)
            rank = _sl_tp_rank(wr, pnl, len(state.trades), tp_h, tp, strategy)
            if rank > best_rank:
                best_rank = rank
                best_sl, best_tp = sl, tp

    top = sorted(
        trials,
        key=lambda t: _sl_tp_rank(t.win_rate, t.total_pnl, t.trades, t.tp_hits, t.take_profit_pct, strategy),
        reverse=True,
    )
    reason = (
        f"설정값 기반 SL/TP 최적화: SL {best_sl}% / TP {best_tp}% "
        f"(기준 SL {base_sl}% TP {base_tp}%, TP상한 {tp_max}%, 후보 {len(trials)}개, score={min_score})"
    )
    if top:
        t0 = top[0]
        reason += f" — 최고 승률 {t0.win_rate}% PnL {t0.total_pnl:+.2f} TP {t0.tp_hits}/{t0.trades}건"
    return best_sl, best_tp, trials, reason


def _profit_protect_rank(win_rate: float, pnl: float, trades: int, protect_hits: int) -> float:
    if trades <= 0:
        return float("-inf")
    protect_rate = protect_hits / trades
    sparse_penalty = max(0, 6 - trades) * 6.0
    over_protect_penalty = max(0.0, protect_rate - 0.45) * 20.0
    return pnl * 1.2 + win_rate * 0.16 + min(trades, 45) * 0.35 + protect_hits * 0.3 - sparse_penalty - over_protect_penalty


def optimize_profit_protection(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
    min_score: float,
    invert_signals: bool,
    window_ratio: float,
) -> tuple[float, int, list[BacktestProfitProtectTrial], str]:
    user_trigger = float(config.profit_protect_trigger_pct) if config.profit_protect_trigger_pct else 3.0
    user_confirm = int(config.profit_protect_confirm_sec) if config.profit_protect_confirm_sec else 10

    trigger_candidates = sorted(set([
        round(max(0.5, user_trigger * 0.5), 2),
        round(max(0.5, user_trigger * 0.75), 2),
        round(max(0.5, user_trigger), 2),
        round(max(0.5, user_trigger * 1.5), 2),
        round(max(0.5, user_trigger * 2.0), 2),
        1.0, 3.0, 5.0, 8.0, 10.0,
    ]))
    confirm_candidates = sorted(set([
        max(5, user_confirm - 10),
        user_confirm,
        user_confirm + 10,
        user_confirm + 20,
        5, 10, 20, 30,
    ]))
    confirm_candidates = sorted(set(c for c in confirm_candidates if c >= 5))

    trials: list[BacktestProfitProtectTrial] = []
    # ★ best_rank를 -inf 대신 실제 탐색 결과가 없을 때 설정값을 유지하도록
    #    trades>0인 trial이 하나라도 있어야 best를 갱신
    best_rank = float("-inf")
    best_trigger = user_trigger
    best_confirm = user_confirm
    found_valid = False  # trades>0인 결과가 하나라도 있는지 추적

    logs.append(BacktestLogEntry(
        ts=_utc_now(), level="info",
        message=f"보호 익절 탐색: TP기준 {trigger_candidates}%, 유지 {confirm_candidates}초",
    ))

    for trigger in trigger_candidates:
        for confirm in confirm_candidates:
            cfg = config.model_copy(deep=True)
            cfg.profit_protect_trigger_pct = trigger
            cfg.profit_protect_confirm_sec = confirm
            state, _ = run_simulation(
                cfg, symbol_candles, [],
                min_score_override=min_score,
                invert_signals=invert_signals,
                window_ratio=window_ratio,
            )
            pnl = sum(t.pnl_usdt for t in state.trades)
            wins = sum(1 for t in state.trades if t.pnl_usdt > 0)
            wr = wins / len(state.trades) * 100 if state.trades else 0.0
            protect_hits = _count_profit_protect_hits(state.trades)
            trial = BacktestProfitProtectTrial(
                trigger_pct_of_tp=trigger, confirm_sec=confirm,
                total_pnl=round(pnl, 2), win_rate=round(wr, 1),
                trades=len(state.trades), protect_hits=protect_hits,
            )
            trials.append(trial)
            # ★ trades=0이면 rank=-inf이므로 best 갱신 안 됨 — 설정값 유지
            if len(state.trades) > 0:
                rank = _profit_protect_rank(wr, pnl, len(state.trades), protect_hits)
                if rank > best_rank:
                    best_rank = rank
                    best_trigger = trigger
                    best_confirm = confirm
                    found_valid = True

    # ★ 유효한 탐색 결과가 없으면 설정값 그대로 반환 (0으로 떨어지지 않음)
    if not found_valid:
        logs.append(BacktestLogEntry(
            ts=_utc_now(), level="warn",
            message=f"보호 익절 탐색: 거래 없음 — 설정값 유지 ({user_trigger}% / {user_confirm}초)",
        ))

    top = sorted(
        trials,
        key=lambda t: _profit_protect_rank(t.win_rate, t.total_pnl, t.trades, t.protect_hits),
        reverse=True,
    )
    reason = f"보호 익절: TP기준 {best_trigger}% / 유지 {best_confirm}초"
    if top and top[0].trades > 0:
        t0 = top[0]
        reason += f" — top PnL {t0.total_pnl:+.2f} 승률 {t0.win_rate}% 보호청산 {t0.protect_hits}/{t0.trades}"
    return best_trigger, best_confirm, top[:20], reason


def optimize_strategy(
    config: AppConfig,
    symbol_candles: dict[str, list[list]],
    logs: list[BacktestLogEntry],
) -> BacktestRecommendation:
    direction_trials: list[BacktestDirectionTrial] = []
    score_trials: list[BacktestScoreTrial] = []
    best_rank = float("-inf")
    best: BacktestDirectionTrial | None = None

    logs.append(BacktestLogEntry(
        ts=_utc_now(), level="info",
        message="방향 탐색: 정방향/역방향 4가지 × 윈도우(100/75/50%) × min_score",
    ))

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
                    trial_cfg, symbol_candles, trial_logs,
                    min_score_override=ms, invert_signals=invert, window_ratio=wratio,
                )
                pnl = sum(t.pnl_usdt for t in state.trades)
                wins = sum(1 for t in state.trades if t.pnl_usdt > 0)
                win_r = wins / len(state.trades) * 100 if state.trades else 0.0
                long_n = sum(1 for t in state.trades if t.side == "long")
                short_n = sum(1 for t in state.trades if t.side == "short")
                dt = BacktestDirectionTrial(
                    mode=mode, window_ratio=wratio, min_score=ms,
                    total_pnl=round(pnl, 2), win_rate=round(win_r, 1),
                    trades=len(state.trades), long_trades=long_n, short_trades=short_n,
                )
                direction_trials.append(dt)
                rank = _trial_rank(pnl, win_r, len(state.trades))
                if rank > best_rank:
                    best_rank = rank
                    best = dt

    if best is None:
        best = BacktestDirectionTrial(
            mode="normal", window_ratio=1.0, min_score=config.min_score,
            total_pnl=0, win_rate=0, trades=0,
        )

    for ms in SCORE_GRID:
        st_logs: list[BacktestLogEntry] = []
        best_cfg = _config_for_direction(config, best.mode)
        st, _ = run_simulation(
            best_cfg, symbol_candles, st_logs,
            min_score_override=ms, invert_signals=best.mode == "inverse", window_ratio=best.window_ratio,
        )
        pnl = sum(t.pnl_usdt for t in st.trades)
        wins = sum(1 for t in st.trades if t.pnl_usdt > 0)
        wr = wins / len(st.trades) * 100 if st.trades else 0
        score_trials.append(BacktestScoreTrial(
            min_score=ms, total_pnl=round(pnl, 2), win_rate=round(wr, 1),
            trades=len(st.trades),
            long_entries=sum(1 for t in st.trades if t.side == "long"),
            short_entries=sum(1 for t in st.trades if t.side == "short"),
        ))

    long_best = max(
        (t for t in direction_trials if t.mode in ("normal", "long_only") and (t.long_trades or 0) > 0),
        key=lambda t: _trial_rank(t.total_pnl, t.win_rate, t.trades), default=None,
    )
    short_best = max(
        (t for t in direction_trials if t.mode in ("short_only", "inverse") and (t.short_trades or 0) > 0),
        key=lambda t: _trial_rank(t.total_pnl, t.win_rate, t.trades), default=None,
    )

    dir_reason = (
        f"최적 {best.mode} 윈도우 {int(best.window_ratio * 100)}% "
        f"min_score={best.min_score} PnL {best.total_pnl:+.2f} 승률 {best.win_rate}%"
    )
    if long_best and short_best and long_best.win_rate < 45 and short_best.win_rate >= long_best.win_rate + 8:
        dir_reason += f" | 롱 승률 {long_best.win_rate}% 낮음 → 숏 전환 {short_best.win_rate}% 권장"

    rec_sl, rec_tp, sl_tp_trials, sl_tp_reason = optimize_sl_tp(
        _config_for_direction(config, best.mode),
        symbol_candles, logs, best.min_score, best.mode == "inverse", best.window_ratio,
    )

    protect_cfg = _config_for_direction(config, best.mode)
    protect_cfg.stop_loss_pct = rec_sl
    protect_cfg.take_profit_pct = rec_tp
    protect_cfg.profit_protect_trigger_pct = config.profit_protect_trigger_pct
    protect_cfg.profit_protect_confirm_sec = config.profit_protect_confirm_sec

    rec_protect_trigger, rec_protect_confirm, protect_trials, protect_reason = optimize_profit_protection(
        protect_cfg, symbol_candles, logs, best.min_score, best.mode == "inverse", best.window_ratio,
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
        profit_protect_trigger_pct=rec_protect_trigger,
        profit_protect_confirm_sec=rec_protect_confirm,
        profit_protect_reason=protect_reason,
        profit_protect_trials=protect_trials,
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

    logs.insert(0, BacktestLogEntry(
        ts=started, level="info",
        message=f"백테스트 시작 id={rid} 종목 {len(symbols)}개 · SL {config.stop_loss_pct}% TP {config.take_profit_pct}% 보호 {config.profit_protect_trigger_pct}%/{config.profit_protect_confirm_sec}초",
    ))

    recommendation = None
    if optimize:
        recommendation = optimize_strategy(config, symbol_candles, logs)
        logs.append(BacktestLogEntry(
            ts=_utc_now(), level="ok",
            message=(
                f"추천 {recommendation.direction} / min_score={recommendation.min_score} "
                f"/ 윈도우 {int(recommendation.window_ratio * 100)}% — {recommendation.reason}"
            ),
        ))

    invert_run = recommendation.direction == "inverse" if recommendation else False
    window_run = recommendation.window_ratio if recommendation else 1.0
    min_run = recommendation.min_score if recommendation else config.min_score

    run_cfg = config.model_copy(deep=True)
    if recommendation:
        run_cfg = _config_for_direction(run_cfg, recommendation.direction)
    if recommendation and recommendation.stop_loss_pct > 0 and recommendation.take_profit_pct > 0:
        run_cfg.stop_loss_pct = recommendation.stop_loss_pct
        run_cfg.take_profit_pct = recommendation.take_profit_pct

    # ★ 보호 익절: 추천값이 유효하면 적용, 아니면 원래 설정값 유지 (0으로 덮어쓰지 않음)
    if recommendation and recommendation.profit_protect_trigger_pct > 0:
        run_cfg.profit_protect_trigger_pct = recommendation.profit_protect_trigger_pct
        run_cfg.profit_protect_confirm_sec = recommendation.profit_protect_confirm_sec
    else:
        # 추천값이 0이거나 없으면 원래 config 설정값 그대로 유지
        run_cfg.profit_protect_trigger_pct = config.profit_protect_trigger_pct
        run_cfg.profit_protect_confirm_sec = config.profit_protect_confirm_sec

    state, bars = run_simulation(
        run_cfg, symbol_candles, logs,
        min_score_override=min_run, invert_signals=invert_run, window_ratio=window_run,
    )
    initial_snap = PortfolioSnapshot(
        balance=start_equity, equity=start_equity, available=start_equity,
        unrealized_pnl=0, realized_pnl=0, positions=[], trade_count=0, win_rate=0,
    )
    order_notional = resolve_order_size_usdt(run_cfg, initial_snap, open_positions=0)
    metrics = _metrics_from_state(state, bars, start_equity, order_notional)

    finished = _utc_now()
    logs.append(BacktestLogEntry(
        ts=finished, level="ok",
        message=(
            f"완료 시작 ${metrics.start_equity:,.0f} → 최종 ${metrics.end_equity:,.0f} "
            f"(손익 {metrics.total_pnl:+.2f} USDT, {metrics.total_pnl_pct:+.2f}%) "
            f"1건 금액 ${metrics.order_notional_usdt:,.0f} · "
            f"거래 {metrics.trade_count}건 승률 {metrics.win_rate}%"
        ),
    ))

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
    logs.append(BacktestLogEntry(
        ts=_utc_now(), level="info",
        message=(
            f"구간 워크포워드: {zone_walkforward.samples}개 샘플, "
            f"정확도 {zone_walkforward.accuracy_pct}% "
            f"(롱 {zone_walkforward.long_accuracy_pct}% / 숏 {zone_walkforward.short_accuracy_pct}%), "
            f"기대값 {zone_walkforward.avg_forward_r}R, 허위돌파 {zone_walkforward.false_break_pct}%"
        ),
    ))

    symbol_profile_data: dict[str, dict] = {}
    if recommendation and symbol_candles:
        from app.backtest.symbol_sl_tp import build_symbol_profiles, persist_profiles_from_backtest

        built = build_symbol_profiles(
            run_cfg, symbol_candles, state.trades, min_run, invert_run, window_run, rid,
        )
        if built:
            merged = persist_profiles_from_backtest(built)
            symbol_profile_data = {k: v.model_dump() for k, v in merged.items()}
            for iid, p in built.items():
                logs.append(BacktestLogEntry(
                    ts=_utc_now(), level="info",
                    message=f"{iid} 종목 SL/TP - SL {p.stop_loss_pct}% TP {p.take_profit_pct}% 승률 {p.win_rate}% ({p.trades}건)",
                ))

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
            "profit_protect_trigger_pct": config.profit_protect_trigger_pct,
            "profit_protect_confirm_sec": config.profit_protect_confirm_sec,
            "stop_loss_pct_applied": run_cfg.stop_loss_pct,
            "take_profit_pct_applied": run_cfg.take_profit_pct,
            "profit_protect_trigger_pct_applied": run_cfg.profit_protect_trigger_pct,
            "profit_protect_confirm_sec_applied": run_cfg.profit_protect_confirm_sec,
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
