"""Instrument sizing rules shared by paper and live execution."""

from __future__ import annotations

from dataclasses import dataclass

from app.market.okx_client import get_okx_client
from app.models import AppConfig, InstrumentType


@dataclass(frozen=True)
class SwapSizingRules:
    ct_val: float = 0.01
    min_sz: float = 1.0
    lot_sz: float = 1.0


def inst_type(config: AppConfig) -> str:
    if config.instrument_type == InstrumentType.SPOT:
        return "SPOT"
    if config.instrument_type == InstrumentType.FUTURES:
        return "FUTURES"
    return "SWAP"


def _float_field(row: dict, key: str, default: float) -> float:
    try:
        value = float(row.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else default


def swap_sizing_rules(config: AppConfig, inst_id: str) -> SwapSizingRules:
    client = get_okx_client(
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_passphrase,
        config.okx_flag,
    )
    meta = client.get_instrument(inst_id, inst_type(config)) or {}
    return SwapSizingRules(
        ct_val=_float_field(meta, "ctVal", 0.01),
        min_sz=_float_field(meta, "minSz", 1.0),
        lot_sz=_float_field(meta, "lotSz", 1.0),
    )
