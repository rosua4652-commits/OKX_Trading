from app.backtest.symbol_sl_tp import (
    SymbolSlTpProfile,
    build_symbol_profiles,
    merge_profiles,
    optimize_symbol_sl_tp,
    resolve_entry_sl_tp,
)
from app.models import AppConfig, StrategyMode


def test_resolve_entry_sl_tp_uses_symbol_profile(tmp_path, monkeypatch):
    from app.backtest import symbol_sl_tp as mod

    monkeypatch.setattr(mod, "PROFILES_FILE", tmp_path / "profiles.json")
    mod.save_profiles(
        {
            "SHIB-USDT-SWAP": SymbolSlTpProfile(
                inst_id="SHIB-USDT-SWAP",
                stop_loss_pct=1.2,
                take_profit_pct=1.5,
                win_rate=82.0,
                trades=5,
                avg_win_tp_pct=1.5,
            )
        }
    )
    cfg = AppConfig(backtest_auto_sl_tp=True)
    out = resolve_entry_sl_tp("SHIB-USDT-SWAP", cfg, StrategyMode.SCALP)
    assert out is not None
    sl, tp, note = out
    assert sl == 1.2
    assert tp == 1.5
    assert "SHIB" in note


def test_resolve_entry_skipped_when_auto_off():
    cfg = AppConfig(backtest_auto_sl_tp=False)
    assert resolve_entry_sl_tp("BTC-USDT-SWAP", cfg, StrategyMode.SCALP) is None


def test_merge_profiles_weighted():
    old = SymbolSlTpProfile(
        inst_id="PEPE-USDT-SWAP",
        stop_loss_pct=2.0,
        take_profit_pct=3.0,
        win_rate=60.0,
        trades=10,
    )
    new = SymbolSlTpProfile(
        inst_id="PEPE-USDT-SWAP",
        stop_loss_pct=1.0,
        take_profit_pct=1.5,
        win_rate=90.0,
        trades=4,
    )
    merged = merge_profiles({"PEPE-USDT-SWAP": old}, {"PEPE-USDT-SWAP": new})
    p = merged["PEPE-USDT-SWAP"]
    assert p.take_profit_pct < 3.0
    assert p.trades == 14
