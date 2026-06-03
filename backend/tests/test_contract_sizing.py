from app.contract_sizing import swap_contract_count, swap_margin_usdt, swap_notional_usdt


def test_swap_notional_matches_order_size():
    price = 100_000.0
    size = 3_000.0
    contracts = swap_contract_count(size, price)
    notional = swap_notional_usdt(contracts, price)
    assert notional <= size * 1.01
    assert notional >= size * 0.5


def test_swap_margin_with_leverage():
    margin = swap_margin_usdt(3000, 3)
    assert margin == 1000
