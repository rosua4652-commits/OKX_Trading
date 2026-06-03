from app.models import AppConfig, PortfolioSnapshot
from app.order_sizing import resolve_order_size_detail, resolve_order_size_usdt


def _snap(equity: float, available: float, n_pos: int = 0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        balance=equity,
        equity=equity,
        available=available,
        unrealized_pnl=0,
        realized_pnl=0,
        positions=[],
        trade_count=0,
        win_rate=0,
    )


def test_fixed_size():
    cfg = AppConfig(order_size_usdt=3000, position_size_mode="fixed")
    assert resolve_order_size_usdt(cfg, _snap(1e6, 988000)) == 3000


def test_pct_available():
    cfg = AppConfig(position_size_mode="pct_available", order_size_pct=2.0)
    assert resolve_order_size_usdt(cfg, _snap(1e6, 100_000)) == 2000


def test_split_slots():
    cfg = AppConfig(
        position_size_mode="pct_available",
        order_size_pct=100,
        max_positions=4,
        size_split_slots=True,
    )
    snap = _snap(1e6, 80_000, n_pos=1)
    size = resolve_order_size_usdt(cfg, snap, open_positions=1)
    assert abs(size - 80_000 / 3) < 1


def test_margin_basis():
    cfg = AppConfig(
        position_size_mode="pct_available",
        order_size_pct=10,
        order_size_basis="margin",
        leverage=10,
    )
    snap = _snap(1e6, 100_000)
    detail = resolve_order_size_detail(cfg, snap)
    assert detail.margin_usdt == 10_000
    assert detail.notional_usdt == 100_000


def test_margin_mode_default_isolated():
    cfg = AppConfig()
    assert cfg.margin_mode == "isolated"
