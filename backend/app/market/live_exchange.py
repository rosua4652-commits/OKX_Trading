"""Live exchange order execution."""

from __future__ import annotations

import logging

from app.contract_sizing import swap_contract_count
from app.market.instrument_rules import swap_sizing_rules
from app.market.okx_client import get_okx_client
from app.models import AppConfig, InstrumentType, PositionSide

logger = logging.getLogger("oat.live")


def _td_mode(config: AppConfig) -> str:
    if config.instrument_type == InstrumentType.SPOT:
        return "cash"
    mode = (getattr(config, "margin_mode", None) or "isolated").lower()
    return "isolated" if mode == "isolated" else "cross"


async def live_open(
    config: AppConfig,
    inst_id: str,
    side: PositionSide,
    size_usdt: float,
) -> tuple[bool, str, float]:
    client = get_okx_client(
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_passphrase,
        config.okx_flag,
    )
    if not client.has_credentials:
        return False, "API credentials are missing", 0.0

    ticker = client.get_ticker(inst_id)
    if not ticker:
        return False, "ticker lookup failed", 0.0
    price = float(ticker.get("last", 0))
    if price <= 0:
        return False, "invalid ticker price", 0.0

    td_mode = _td_mode(config)
    if config.instrument_type != InstrumentType.SPOT:
        client.set_leverage(
            inst_id,
            config.leverage,
            td_mode,
            pos_side=side.value if td_mode == "isolated" else "",
        )

    if config.instrument_type == InstrumentType.SPOT:
        if side == PositionSide.LONG:
            sz = str(round(size_usdt, 6))
            order_side = "buy"
        else:
            sz = str(round(size_usdt / price, 6))
            order_side = "sell"
        pos_side = ""
    else:
        rules = swap_sizing_rules(config, inst_id)
        contracts = swap_contract_count(
            size_usdt,
            price,
            rules.ct_val,
            rules.min_sz,
            rules.lot_sz,
        )
        sz = f"{contracts:.12f}".rstrip("0").rstrip(".")
        order_side = "buy" if side == PositionSide.LONG else "sell"
        pos_side = side.value

    result = client.place_order(
        inst_id=inst_id,
        side=order_side,
        sz=sz,
        td_mode=td_mode,
        pos_side=pos_side or "long",
    )
    if result:
        return True, f"order accepted ordId={result.get('ordId', '')}", price
    return False, f"order failed: {client.last_error or 'unknown'}", 0.0


async def live_close(
    config: AppConfig,
    inst_id: str,
    side: PositionSide,
    quantity: float,
) -> tuple[bool, str]:
    client = get_okx_client(
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_passphrase,
        config.okx_flag,
    )
    if not client.has_credentials:
        return False, "API credentials are missing"

    td_mode = _td_mode(config)
    if quantity <= 0:
        return False, "invalid close quantity"
    sz = (
        f"{quantity:.12f}".rstrip("0").rstrip(".")
        if config.instrument_type != InstrumentType.SPOT
        else str(round(quantity, 6))
    )
    result = client.close_position(inst_id, side.value, sz, td_mode)
    if result:
        return True, f"close accepted ordId={result.get('ordId', '')}"
    return False, f"close failed: {client.last_error or 'unknown'}"


async def test_connection(config: AppConfig) -> tuple[bool, str]:
    client = get_okx_client(
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_passphrase,
        config.okx_flag,
    )
    return client.test_connection()
