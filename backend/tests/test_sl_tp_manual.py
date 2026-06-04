from app.engine.portfolio import PortfolioManager
from app.engine.exit_rules import should_exit
from app.models import AppConfig, InstrumentType, PositionSide, StrategyMode, TradeMode
from app.sl_tp_utils import sl_tp_prices_from_pct, validate_sl_tp


def test_sl_tp_prices_long():
    sl, tp = sl_tp_prices_from_pct(100.0, PositionSide.LONG, 2.0, 4.0)
    assert sl == 98.0
    assert tp == 104.0


def test_sl_tp_prices_short_are_reversed():
    sl, tp = sl_tp_prices_from_pct(100.0, PositionSide.SHORT, 2.0, 4.0)
    assert sl == 102.0
    assert tp == 96.0


def test_manual_sl_tp_persisted():
    pm = PortfolioManager(TradeMode.PAPER, 10_000)
    cfg = AppConfig(instrument_type=InstrumentType.SWAP, leverage=10)
    pm.open_position(
        "BTC-USDT-SWAP",
        PositionSide.LONG,
        1,
        100_000,
        cfg,
        strategy_mode=StrategyMode.SCALP,
        notional_usdt=1000,
    )
    ok, _ = pm.set_sl_tp_manual("BTC-USDT-SWAP", 1.5, 5.0)
    assert ok
    pos = pm.positions["BTC-USDT-SWAP"]
    assert pos.sl_tp_manual
    assert pos.sl_pct == 1.5
    assert pos.tp_pct == 5.0
    assert pos.stop_loss < pos.entry_price
    assert pos.take_profit > pos.entry_price


def test_validate_short():
    err = validate_sl_tp(1.0, PositionSide.SHORT, 2.0, 3.0)
    assert err is None


def test_auto_sl_tp_disabled_skips_exit():
    pm = PortfolioManager(TradeMode.PAPER, 10_000)
    cfg = AppConfig(instrument_type=InstrumentType.SWAP, leverage=10)
    pos = pm.open_position(
        "BTC-USDT-SWAP",
        PositionSide.LONG,
        1,
        100,
        cfg,
        strategy_mode=StrategyMode.SCALP,
        stop_loss=98,
        take_profit=103,
        sl_pct=2,
        tp_pct=3,
        notional_usdt=1000,
    )
    assert pos
    pos.current_price = 97
    pos.auto_sl_tp_disabled = True
    exit_flag, _ = should_exit(pos, cfg)
    assert not exit_flag
