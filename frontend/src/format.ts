export function fmtNum(n: number, digits = 2) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtUsd(n: number, digits = 2) {
  if (!Number.isFinite(n)) return "-";
  return `$${fmtNum(n, digits)}`;
}

export function fmtPnlUsdt(n: number) {
  if (!Number.isFinite(n)) return "0.0000";
  const abs = Math.abs(n);
  const digits = abs < 0.01 ? 5 : abs < 1 ? 4 : 3;
  return fmtNum(n, digits);
}

export function fmtPrice(n: number) {
  if (!Number.isFinite(n) || n <= 0) return "-";
  if (n >= 1000) {
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  const maxFrac = n >= 1 ? 4 : n >= 0.01 ? 5 : n >= 0.0001 ? 7 : 12;
  return n.toLocaleString(undefined, {
    useGrouping: n >= 1,
    minimumFractionDigits: 0,
    maximumFractionDigits: maxFrac,
  });
}

export function fmtVolumeUsdt(usdt: number) {
  if (!Number.isFinite(usdt) || usdt <= 0) return "-";
  if (usdt >= 1e9) return `${(usdt / 1e9).toFixed(2)}B`;
  if (usdt >= 1e6) return `${(usdt / 1e6).toFixed(2)}M`;
  if (usdt >= 1e3) return `${(usdt / 1e3).toFixed(1)}K`;
  return usdt.toFixed(0);
}

export function slTpFromPrices(
  entry: number,
  sl: number,
  tp: number,
  side: string,
  leverage = 1,
  instrumentType = "swap",
): { slPct: number; tpPct: number } {
  if (entry <= 0) return { slPct: 0, tpPct: 0 };
  const lev = instrumentType === "spot" ? 1 : Math.max(1, leverage || 1);
  if (side === "short") {
    return {
      slPct: ((sl - entry) / entry) * 100 * lev,
      tpPct: ((entry - tp) / entry) * 100 * lev,
    };
  }
  return {
    slPct: ((entry - sl) / entry) * 100 * lev,
    tpPct: ((tp - entry) / entry) * 100 * lev,
  };
}

export function fmtSlTpCell(
  entry: number,
  sl: number,
  tp: number,
  side: string,
  strategyMode?: string,
  storedSlPct?: number,
  storedTpPct?: number,
  slTpNote?: string,
  leverage = 1,
  instrumentType = "swap",
) {
  const fromPrices = slTpFromPrices(entry, sl, tp, side, leverage, instrumentType);
  const slPct = storedSlPct && storedSlPct > 0 ? storedSlPct : Math.abs(fromPrices.slPct);
  const tpPct = storedTpPct && storedTpPct > 0 ? storedTpPct : Math.abs(fromPrices.tpPct);
  const strat =
    strategyMode === "swing" ? "장타" : strategyMode === "both" ? "복합" : "단타";
  const note = slTpNote ? ` · ${slTpNote}` : "";
  return {
    text: `[${strat}] PnL SL -${fmtNum(slPct, 1)}% / TP +${fmtNum(tpPct, 1)}%`,
    detail: `SL ${fmtPrice(sl)} · TP ${fmtPrice(tp)}${note}`,
    slPct,
    tpPct,
  };
}
