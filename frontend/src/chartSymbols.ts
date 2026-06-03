/** OKX inst_id → TradingView symbol (with fallbacks for altcoins) */

/** OKX perpetual symbols commonly listed on TradingView */
const OKX_PERP_ON_TV = new Set([
  "BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "LINK", "DOT", "MATIC",
  "POL", "LTC", "BCH", "UNI", "ATOM", "ETC", "FIL", "APT", "ARB", "OP",
  "SUI", "NEAR", "INJ", "TIA", "SEI", "PEPE", "WIF", "BONK", "NOT",
]);

export function parseInstBase(instId: string): string {
  if (instId.endsWith("-USDT-SWAP")) {
    return instId.slice(0, -"-USDT-SWAP".length);
  }
  if (instId.endsWith("-USDT")) {
    return instId.slice(0, -"-USDT".length);
  }
  const parts = instId.split("-");
  return parts[0] || instId;
}

export type TvSymbolOption = {
  id: string;
  label: string;
  symbol: string;
};

/** Candidate symbols to try (first = default embed) */
export function tradingViewSymbolOptions(instId: string): TvSymbolOption[] {
  const base = parseInstBase(instId);
  const opts: TvSymbolOption[] = [];

  if (instId.endsWith("-SWAP")) {
    if (OKX_PERP_ON_TV.has(base)) {
      opts.push({
        id: "okx-swap",
        label: `OKX ${base} 무기한`,
        symbol: `OKX:${base}USDT.P`,
      });
    }
    opts.push({
      id: "binance-swap",
      label: `Binance ${base} PERP (참고)`,
      symbol: `BINANCE:${base}USDT.P`,
    });
    opts.push({
      id: "okx-spot",
      label: `OKX ${base} 현물`,
      symbol: `OKX:${base}USDT`,
    });
  } else if (instId.endsWith("-USDT")) {
    opts.push({
      id: "okx-spot",
      label: `OKX ${base} 현물`,
      symbol: `OKX:${base}USDT`,
    });
    opts.push({
      id: "binance-spot",
      label: `Binance ${base}`,
      symbol: `BINANCE:${base}USDT`,
    });
  } else {
    opts.push({
      id: "raw",
      label: instId,
      symbol: `OKX:${instId.replace(/-/g, "")}`,
    });
  }

  const seen = new Set<string>();
  return opts.filter((o) => {
    if (seen.has(o.symbol)) return false;
    seen.add(o.symbol);
    return true;
  });
}

/** Default embed symbol — altcoins use Binance PERP when OKX.P missing on TV */
export function toTradingViewSymbol(instId: string): string {
  const opts = tradingViewSymbolOptions(instId);
  return opts[0]?.symbol ?? `BINANCE:${parseInstBase(instId)}USDT.P`;
}

export function strategyToTvInterval(strategy: string): string {
  return strategy === "swing" ? "60" : "5";
}

export function strategyToBarLabel(strategy: string): string {
  if (strategy === "swing") return "1시간봉";
  if (strategy === "both") return "5분·1시간";
  return "5분봉";
}
