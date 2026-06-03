"""Risk management checks."""

from __future__ import annotations

from app.contract_sizing import swap_margin_usdt
from app.order_sizing import resolve_order_size_usdt
from app.models import (
    AppConfig,
    CoinCandidate,
    InstrumentType,
    PortfolioSnapshot,
    PositionSide,
    StrategyMode,
)


def _is_short_entry(candidate: CoinCandidate, entry_side: PositionSide | None) -> bool:
    if entry_side == PositionSide.SHORT:
        return True
    if entry_side == PositionSide.LONG:
        return False
    return candidate.outlook == "short"


def check_entry_allowed(
    config: AppConfig,
    portfolio: PortfolioSnapshot,
    candidate: CoinCandidate,
    strategy: StrategyMode | None = None,
    entry_side: PositionSide | None = None,
) -> tuple[bool, str]:
    if len(portfolio.positions) >= config.max_positions:
        return False, f"최대 포지션 ({config.max_positions}) 도달"

    need = resolve_order_size_usdt(
        config,
        portfolio,
        open_positions=len(portfolio.positions),
    )
    if config.instrument_type != InstrumentType.SPOT:
        need_margin = swap_margin_usdt(need, config.leverage)
    else:
        need_margin = need
    if portfolio.available < need_margin:
        return False, f"가용 잔고 부족 (마진 ${need_margin:,.0f} 필요)"

    for pos in portfolio.positions:
        if pos.inst_id == candidate.inst_id:
            return False, "이미 보유 중"

    daily_loss_limit = portfolio.balance * 0.05
    if portfolio.realized_pnl < -daily_loss_limit:
        return False, "일일 손실 한도 초과"

    strat = strategy or config.strategy_mode
    if strat == StrategyMode.BOTH:
        strat = StrategyMode.SCALP

    is_short = _is_short_entry(candidate, entry_side)

    if is_short:
        if not config.allow_short:
            return False, "숏 비허용 (설정 확인)"
        if config.instrument_type == InstrumentType.SPOT:
            return False, "현물은 숏 불가"
        if strat == StrategyMode.SCALP:
            if not candidate.short_scalp_ok and candidate.outlook != "short":
                return False, f"단타 숏 조건 미충족 (score={candidate.score})"
            if candidate.score < config.min_score - 5:
                return False, f"숏 점수 부족 ({candidate.score})"
        else:
            if not candidate.short_swing_ok and candidate.outlook != "short":
                return False, f"장타 숏 조건 미충족 (score={candidate.score})"
            if candidate.score < config.min_score - 8:
                return False, f"숏 점수 부족 ({candidate.score})"
        if candidate.trend not in ("down", "sideways"):
            return False, f"숏: 추세 부적합 ({candidate.trend})"
        return True, "OK (숏)"

    if strat == StrategyMode.SCALP:
        if not candidate.scalp_ok:
            return False, f"단타 롱 조건 미충족 (score={candidate.score})"
        if candidate.score < config.min_score:
            return False, f"점수 부족 ({candidate.score} < {config.min_score})"
    elif strat == StrategyMode.SWING:
        if not candidate.swing_ok:
            return False, f"장타 롱 조건 미충족 (score={candidate.score})"
        if candidate.score < config.min_score - 5:
            return False, f"점수 부족 ({candidate.score})"
    else:
        return False, "전략 미지정"

    return True, "OK (롱)"
