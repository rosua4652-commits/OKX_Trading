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


def test_swap_contract_count_respects_okx_min_and_lot():
    contracts = swap_contract_count(4.9, price=100, ct_val=0.1, min_sz=0.5, lot_sz=0.5)
    assert contracts == 0.5
    assert swap_contract_count(26, price=100, ct_val=0.1, min_sz=0.5, lot_sz=0.5) == 2.5
