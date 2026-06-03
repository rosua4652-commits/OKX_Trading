"""Convert OKX candles for backtest UI mini charts."""

from __future__ import annotations

from app.backtest.models import BacktestTrade, SymbolCandleChart


def _row_to_bar(row: list) -> dict[str, float] | None:
    if len(row) < 5:
        return None
    try:
        return {
            "o": float(row[1]),
            "h": float(row[2]),
            "l": float(row[3]),
            "c": float(row[4]),
        }
    except (TypeError, ValueError):
        return None


def build_symbol_charts(
    symbol_candles: dict[str, list],
    trades: list[BacktestTrade],
    display_bars: int = 56,
) -> dict[str, SymbolCandleChart]:
    trades_by_inst: dict[str, list[BacktestTrade]] = {}
    for t in trades:
        trades_by_inst.setdefault(t.inst_id, []).append(t)

    out: dict[str, SymbolCandleChart] = {}
    for inst_id, candles in symbol_candles.items():
        all_bars: list[dict[str, float]] = []
        for row in candles:
            b = _row_to_bar(row)
            if b:
                all_bars.append(b)

        if len(all_bars) < 2:
            continue

        total = len(all_bars)
        start = max(0, total - display_bars)
        slice_bars = all_bars[start:]
        markers: list[dict[str, int]] = []
        for t in trades_by_inst.get(inst_id, []):
            if t.entry_bar >= start and t.entry_bar < total:
                markers.append({
                    "entry": t.entry_bar - start,
                    "exit": t.exit_bar - start if start <= t.exit_bar < total else -1,
                })

        out[inst_id] = SymbolCandleChart(
            bars=slice_bars,
            total_bars=total,
            display_offset=start,
            trade_markers=markers,
        )
    return out
