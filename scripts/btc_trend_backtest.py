from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import random


@dataclass
class Bar:
    ts: datetime
    close: float
    volume: float
    regime: str


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def make_data() -> list[Bar]:
    random.seed(20260606)
    start = datetime(2021, 1, 1)
    end = datetime(2026, 6, 6)
    regimes = [
        (datetime(2021, 1, 1), datetime(2021, 12, 31, 23), "2021 bull", 0.00038, 0.024, 1.45),
        (datetime(2022, 1, 1), datetime(2022, 12, 31, 23), "2022 bear", -0.00034, 0.027, 1.55),
        (datetime(2023, 1, 1), datetime(2024, 12, 31, 23), "2023-2024 recovery", 0.00022, 0.019, 1.15),
        (datetime(2025, 1, 1), end, "2025-2026 chop", 0.00002, 0.022, 1.35),
    ]
    price = 29300.0
    out: list[Bar] = []
    ts = start
    while ts <= end:
        for s, e, name, drift, vol, vol_scale in regimes:
            if s <= ts <= e:
                regime = name
                break
        shock = random.gauss(drift, vol)
        cyc = math.sin(len(out) / 90) * vol * 0.18 + math.sin(len(out) / 420) * vol * 0.25
        price = max(3200, price * math.exp(shock + cyc))
        base_vol = 1200 * vol_scale * (1 + abs(shock) * 18)
        volume = max(100, random.lognormvariate(math.log(base_vol), 0.55))
        out.append(Bar(ts, price, volume, regime))
        ts += timedelta(hours=1)
    return out


def backtest(bars: list[Bar]) -> dict:
    closes = [b.close for b in bars]
    vols = [b.volume for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    equity = 10_000.0
    peak = equity
    mdd = 0.0
    pos = None
    trades = []
    regime_pnl: dict[str, list[float]] = {}
    friction = 0.001
    for i in range(51, len(bars)):
        price = closes[i]
        if pos:
            entry, regime = pos
            raw = (price - entry) / entry
            exit_reason = None
            if raw <= -0.015:
                exit_reason = "SL"
                raw = -0.015
            elif raw >= 0.03:
                exit_reason = "TP"
                raw = 0.03
            if exit_reason:
                net = raw - friction
                pnl = equity * net
                equity += pnl
                trades.append((net, pnl, exit_reason, regime))
                regime_pnl.setdefault(regime, []).append(pnl)
                peak = max(peak, equity)
                mdd = min(mdd, (equity - peak) / peak)
                pos = None
            continue

        vol_ma = sum(vols[i - 20:i]) / 20
        cross = e20[i - 1] <= e50[i - 1] and e20[i] > e50[i]
        if cross and vols[i] >= vol_ma * 1.5:
            pos = (price * 1.0005, bars[i].regime)

    wins = [t for t in trades if t[1] > 0]
    losses = [t for t in trades if t[1] < 0]
    gross_win = sum(t[1] for t in wins)
    gross_loss = abs(sum(t[1] for t in losses))
    months = max(1, (bars[-1].ts.year - bars[0].ts.year) * 12 + bars[-1].ts.month - bars[0].ts.month + 1)
    result = {
        "total_roi": (equity / 10_000 - 1) * 100,
        "pf": gross_win / gross_loss if gross_loss else 0,
        "mdd": mdd * 100,
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "trades": len(trades),
        "avg_monthly": (equity - 10_000) / months,
        "net_r": sum(t[0] / 0.015 for t in trades),
        "regimes": {},
    }
    for regime, pnls in regime_pnl.items():
        r_w = sum(p for p in pnls if p > 0)
        r_l = abs(sum(p for p in pnls if p < 0))
        result["regimes"][regime] = {
            "roi": sum(pnls) / 10_000 * 100,
            "pf": r_w / r_l if r_l else 0,
            "trades": len(pnls),
        }
    return result


if __name__ == "__main__":
    res = backtest(make_data())
    print(res)
