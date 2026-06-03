"""Risk management checks."""

from __future__ import annotations

from app.models import AppConfig, CoinCandidate, PortfolioSnapshot, StrategyMode


def check_entry_allowed(
    config: AppConfig,
    portfolio: PortfolioSnapshot,
    candidate: CoinCandidate,
) -> tuple[bool, str]:
    if len(portfolio.positions) >= config.max_positions:
        return False, f"최대 포지션 ({config.max_positions}) 도달"

    if portfolio.available < config.order_size_usdt:
        return False, "가용 잔고 부족"

    if config.strategy_mode == StrategyMode.SCALP:
        if not candidate.scalp_ok:
            return False, f"단타 조건 미충족 (score={candidate.score})"
        if candidate.score < config.min_score:
            return False, f"점수 부족 ({candidate.score} < {config.min_score})"
    else:
        if not candidate.swing_ok:
            return False, f"스윙 조건 미충족 (score={candidate.score})"
        if candidate.score < config.min_score - 5:
            return False, f"점수 부족 ({candidate.score})"

    for pos in portfolio.positions:
        if pos.inst_id == candidate.inst_id:
            return False, "이미 보유 중"

    daily_loss_limit = portfolio.balance * 0.05
    if portfolio.realized_pnl < -daily_loss_limit:
        return False, "일일 손실 한도 초과"

    return True, "OK"
