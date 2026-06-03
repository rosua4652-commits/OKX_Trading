import type { AppConfig, Portfolio } from "./types";

export function previewOrderSizeUsdt(
  config: AppConfig,
  portfolio: Portfolio,
): number {
  const mode = config.position_size_mode || "fixed";
  const pct = config.order_size_pct ?? 2;
  const cap = config.max_order_size_usdt ?? 0;
  const minSz = config.min_order_size_usdt ?? 10;
  const open = portfolio.positions.length;

  let size: number;
  if (mode === "pct_equity") {
    size = portfolio.equity * (pct / 100);
  } else if (mode === "pct_available") {
    let base = portfolio.available;
    if (config.size_split_slots && config.max_positions > 0) {
      const slots = Math.max(1, config.max_positions - open);
      base = portfolio.available / slots;
    }
    size = base * (pct / 100);
  } else {
    size = config.order_size_usdt;
  }

  size = Math.max(minSz, size);
  if (cap > 0) size = Math.min(cap, size);
  return Math.round(size * 100) / 100;
}

export function positionSizeModeLabel(mode?: string): string {
  if (mode === "pct_available") return "가용 잔고 %";
  if (mode === "pct_equity") return "총자산(Equity) %";
  return "고정 USDT";
}
