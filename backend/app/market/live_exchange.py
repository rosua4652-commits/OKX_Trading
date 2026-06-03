"""Live exchange order execution."""

from __future__ import annotations

import logging

from app.contract_sizing import swap_contract_count
from app.market.okx_client import get_okx_client
from app.models import AppConfig, InstrumentType, PositionSide

logger = logging.getLogger("oat.live")


def _td_mode(instrument: InstrumentType) -> str:
    if instrument == InstrumentType.SPOT:
        return "cash"
    return "cross"


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
        return False, "API 키 없음", 0.0

    ticker = client.get_ticker(inst_id)
    if not ticker:
        return False, "시세 조회 실패", 0.0
    price = float(ticker.get("last", 0))
    if price <= 0:
        return False, "가격 오류", 0.0

    td_mode = _td_mode(config.instrument_type)
    if config.instrument_type != InstrumentType.SPOT:
        client.set_leverage(inst_id, config.leverage, td_mode)

    if config.instrument_type == InstrumentType.SPOT:
        if side == PositionSide.LONG:
            sz = str(round(size_usdt / price, 6))
            order_side = "buy"
        else:
            sz = str(round(size_usdt / price, 6))
            order_side = "sell"
        pos_side = ""
    else:
        sz = str(int(swap_contract_count(size_usdt, price)))
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
        return True, f"주문 성공 ordId={result.get('ordId', '')}", price
    return False, "주문 실패", 0.0


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
        return False, "API 키 없음"

    td_mode = _td_mode(config.instrument_type)
    sz = (
        str(max(1, int(quantity)))
        if config.instrument_type != InstrumentType.SPOT
        else str(round(quantity, 6))
    )
    result = client.close_position(inst_id, side.value, sz, td_mode)
    if result:
        return True, f"청산 성공 ordId={result.get('ordId', '')}"
    return False, "청산 실패"


async def test_connection(config: AppConfig) -> tuple[bool, str]:
    client = get_okx_client(
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_passphrase,
        config.okx_flag,
    )
    return client.test_connection()
