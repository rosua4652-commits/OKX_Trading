"""SWAP contract count and notional (shared by paper and live)."""

from __future__ import annotations

import math

DEFAULT_CT_VAL = 0.01


def floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step


def swap_contract_count(
    size_usdt: float,
    price: float,
    ct_val: float = DEFAULT_CT_VAL,
    min_sz: float = 1.0,
    lot_sz: float = 1.0,
) -> float:
    if price <= 0 or ct_val <= 0:
        return max(min_sz, 1.0)
    raw = size_usdt / (price * ct_val)
    contracts = floor_to_step(raw, lot_sz)
    return float(max(min_sz, contracts))


def swap_notional_usdt(
    contracts: float,
    price: float,
    ct_val: float = DEFAULT_CT_VAL,
) -> float:
    return contracts * price * ct_val


def swap_margin_usdt(notional: float, leverage: int) -> float:
    return notional / max(1, leverage)


def classify_close_type(reason: str) -> str:
    r = reason or ""
    if "손절" in r:
        return "sl"
    if "익절" in r:
        return "tp"
    if "트레일" in r or "trailing" in r.lower():
        return "trail"
    if "긴급" in r:
        return "emergency"
    if "수동" in r or "manual" in r.lower():
        return "manual"
    return "other"
