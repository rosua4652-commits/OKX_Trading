from app.market.live_account import _okx_to_position
from app.models import AppConfig, InstrumentType, PositionSide


def test_net_mode_negative_position_is_short_with_reversed_sl_tp():
    cfg = AppConfig(instrument_type=InstrumentType.SWAP, stop_loss_pct=2.0, take_profit_pct=3.0)
    pos = _okx_to_position(
        {
            "instId": "BOME-USDT-SWAP",
            "pos": "-40",
            "posSide": "net",
            "avgPx": "0.000434",
            "markPx": "0.0004364",
            "upl": "-0.09",
            "uplRatio": "-0.0541",
            "lever": "10",
            "notionalUsd": "17.45",
        },
        cfg,
        None,
    )
    assert pos is not None
    assert pos.side == PositionSide.SHORT
    assert pos.stop_loss > pos.entry_price
    assert pos.take_profit < pos.entry_price
    assert pos.notional_usdt == 17.45
