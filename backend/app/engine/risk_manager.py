"""Risk management checks."""

from __future__ import annotations

from app.order_sizing import entry_cost_usdt, resolve_order_size_usdt
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
        return False, f"최대 포지션({config.max_positions}) 도달"

    need = resolve_order_size_usdt(
        config,
        portfolio,
        open_positions=len(portfolio.positions),
    )
    need_cost = entry_cost_usdt(config, need)
    if portfolio.available < need_cost:
        return False, f"available balance too low (need margin+fee ${need_cost:,.2f})"

    for pos in portfolio.positions:
        if pos.inst_id == candidate.inst_id:
            return False, "already holding this instrument"

    daily_loss_limit = portfolio.balance * 0.05
    if portfolio.realized_pnl < -daily_loss_limit:
        return False, "daily loss limit exceeded"

    strat = strategy or config.strategy_mode
    if strat == StrategyMode.BOTH:
        strat = StrategyMode.SCALP

    is_short = _is_short_entry(candidate, entry_side)

    if is_short:
        if not config.allow_short:
            return False, "short entries are disabled"
        if config.instrument_type == InstrumentType.SPOT:
            return False, "spot short entries are not supported"
        if strat == StrategyMode.SCALP:
            if not candidate.short_scalp_ok and candidate.outlook != "short":
                return False, f"short scalp conditions not met (score={candidate.score})"
            if candidate.score < config.min_score - 5:
                return False, f"short score too low ({candidate.score})"
        else:
            if not candidate.short_swing_ok and candidate.outlook != "short":
                return False, f"short swing conditions not met (score={candidate.score})"
            if candidate.score < config.min_score - 8:
                return False, f"short score too low ({candidate.score})"
        if candidate.trend not in ("down", "sideways"):
            return False, f"short trend mismatch ({candidate.trend})"
        return True, "OK (숏)"

    if strat == StrategyMode.SCALP:
        if not candidate.scalp_ok:
            return False, f"long scalp conditions not met (score={candidate.score})"
        if candidate.score < config.min_score:
            return False, f"score too low ({candidate.score} < {config.min_score})"
    elif strat == StrategyMode.SWING:
        if not candidate.swing_ok:
            return False, f"long swing conditions not met (score={candidate.score})"
        if candidate.score < config.min_score - 5:
            return False, f"score too low ({candidate.score})"
    else:
        return False, "unsupported strategy"

    return True, "OK (롱)"
