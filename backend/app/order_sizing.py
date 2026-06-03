"""Resolve order notional (USDT) from config and portfolio."""

from __future__ import annotations

from dataclasses import dataclass

from app.contract_sizing import swap_margin_usdt
from app.models import AppConfig, PortfolioSnapshot


@dataclass
class OrderSizeDetail:
    notional_usdt: float
    margin_usdt: float
    leverage: int
    base_usdt: float
    pct: float
    position_size_mode: str
    order_size_basis: str
    size_split_slots: bool
    open_positions: int
    max_positions: int
    slots_remaining: int
    available_usdt: float
    summary: str
    steps: list[str]


def _slot_base(config: AppConfig, portfolio: PortfolioSnapshot, open_positions: int | None) -> tuple[float, int]:
    open_n = open_positions if open_positions is not None else len(portfolio.positions)
    if (
        getattr(config, "size_split_slots", False)
        and config.max_positions > 0
        and config.position_size_mode in ("pct_available", "pct_equity")
    ):
        slots = max(1, config.max_positions - open_n)
        if config.position_size_mode == "pct_equity":
            return portfolio.equity / slots, slots
        return portfolio.available / slots, slots
    if config.position_size_mode == "pct_equity":
        return portfolio.equity, 1
    if config.position_size_mode == "pct_available":
        return portfolio.available, 1
    return 0.0, 1


def resolve_order_size_detail(
    config: AppConfig,
    portfolio: PortfolioSnapshot,
    open_positions: int | None = None,
) -> OrderSizeDetail:
    """Notional USDT per entry; margin = notional / leverage (unless basis=margin)."""
    mode = getattr(config, "position_size_mode", "fixed") or "fixed"
    pct = getattr(config, "order_size_pct", 2.0) or 2.0
    cap = getattr(config, "max_order_size_usdt", 0.0) or 0.0
    min_sz = getattr(config, "min_order_size_usdt", 10.0) or 10.0
    basis = getattr(config, "order_size_basis", "notional") or "notional"
    lev = max(1, int(config.leverage or 1))
    open_n = open_positions if open_positions is not None else len(portfolio.positions)
    split = bool(getattr(config, "size_split_slots", False))

    steps: list[str] = []
    base = 0.0
    slots = 1

    if mode == "fixed":
        notional = float(config.order_size_usdt)
        steps.append(f"고정 주문 명목 ${notional:,.0f}")
    else:
        base, slots = _slot_base(config, portfolio, open_positions)
        if split and config.max_positions > 0:
            src = "총자산" if mode == "pct_equity" else "가용"
            amt = portfolio.equity if mode == "pct_equity" else portfolio.available
            steps.append(
                f"{src} ${amt:,.0f} ÷ 남은슬롯 {slots}개 = ${base:,.0f}/슬롯"
            )
        else:
            src = "총자산(Equity)" if mode == "pct_equity" else "가용 잔고"
            steps.append(f"{src} ${base:,.0f}")

        if basis == "margin":
            margin_raw = base * pct / 100.0
            notional = margin_raw * lev
            steps.append(f"× {pct:g}% = 증거금 ${margin_raw:,.0f}")
            steps.append(f"× 레버 {lev}x = 명목(포지션) ${notional:,.0f}")
        else:
            notional = base * pct / 100.0
            steps.append(f"× {pct:g}% = 명목(포지션) ${notional:,.0f}")
            steps.append(f"÷ 레버 {lev}x = 증거금 ${notional / lev:,.0f}")

    notional = max(min_sz, notional)
    if cap > 0:
        notional = min(cap, notional)

    notional = round(notional, 2)
    margin = round(swap_margin_usdt(notional, lev), 2)

    if mode != "fixed" and basis == "notional" and len(steps) >= 2:
        steps[-1] = f"÷ 레버 {lev}x = 증거금 ${margin:,.0f}"

    basis_label = "증거금 %" if basis == "margin" else "명목(포지션) %"
    split_note = f", 슬롯당 {pct:g}%" if split and slots > 1 else f", {pct:g}%"
    summary = (
        f"명목 ${notional:,.0f} · 증거금 ${margin:,.0f} "
        f"({basis_label}{split_note}, 레버 {lev}x)"
    )

    return OrderSizeDetail(
        notional_usdt=notional,
        margin_usdt=margin,
        leverage=lev,
        base_usdt=round(base, 2),
        pct=pct,
        position_size_mode=mode,
        order_size_basis=basis,
        size_split_slots=split,
        open_positions=open_n,
        max_positions=config.max_positions,
        slots_remaining=slots,
        available_usdt=round(portfolio.available, 2),
        summary=summary,
        steps=steps,
    )


def resolve_order_size_usdt(
    config: AppConfig,
    portfolio: PortfolioSnapshot,
    open_positions: int | None = None,
) -> float:
    return resolve_order_size_detail(config, portfolio, open_positions).notional_usdt
