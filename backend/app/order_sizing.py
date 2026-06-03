"""Resolve order notional (USDT) from config and portfolio."""

from __future__ import annotations

from app.models import AppConfig, PortfolioSnapshot


def resolve_order_size_usdt(
    config: AppConfig,
    portfolio: PortfolioSnapshot,
    open_positions: int | None = None,
) -> float:
    """Notional USDT per entry (before leverage margin = notional/leverage)."""
    mode = getattr(config, "position_size_mode", "fixed") or "fixed"
    pct = getattr(config, "order_size_pct", 2.0) or 2.0
    cap = getattr(config, "max_order_size_usdt", 0.0) or 0.0
    min_sz = getattr(config, "min_order_size_usdt", 10.0) or 10.0

    if mode == "pct_equity":
        base = portfolio.equity
        size = base * pct / 100.0
    elif mode == "pct_available":
        base = portfolio.available
        if getattr(config, "size_split_slots", False) and config.max_positions > 0:
            slots = max(1, config.max_positions - (open_positions or len(portfolio.positions)))
            base = portfolio.available / slots
        size = base * pct / 100.0
    else:
        size = config.order_size_usdt

    size = max(min_sz, size)
    if cap > 0:
        size = min(cap, size)
    return round(size, 2)
