/** Map OKX inst_id to TradingView symbol. */
export function instToTvSymbol(instId: string): string {
  const id = instId.toUpperCase();
  if (id.endsWith("-SWAP") || id.includes("SWAP")) {
    const pair = id.replace("-SWAP", "").replace(/-/g, "");
    return `OKX:${pair}.P`;
  }
  if (id.endsWith("-FUTURES")) {
    const pair = id.replace("-FUTURES", "").replace(/-/g, "");
    return `OKX:${pair}.P`;
  }
  const pair = id.replace(/-/g, "");
  return `OKX:${pair}`;
}

export function strategyToTvInterval(strategy: string): string {
  return strategy === "swing" ? "60" : "5";
}
