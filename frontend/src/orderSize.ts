import type { AppConfig, Portfolio } from "./types";

export interface OrderSizeDetail {
  notionalUsdt: number;
  marginUsdt: number;
  leverage: number;
  baseUsdt: number;
  pct: number;
  slotsRemaining: number;
  openPositions: number;
  steps: string[];
  summary: string;
}

function slotBase(
  config: AppConfig,
  portfolio: Portfolio,
): { base: number; slots: number } {
  const open = portfolio.positions.length;
  const split = !!config.size_split_slots && config.max_positions > 0;
  if (split && config.position_size_mode !== "fixed") {
    const slots = Math.max(1, config.max_positions - open);
    const amt =
      config.position_size_mode === "pct_equity"
        ? portfolio.equity
        : portfolio.available;
    return { base: amt / slots, slots };
  }
  if (config.position_size_mode === "pct_equity") {
    return { base: portfolio.equity, slots: 1 };
  }
  if (config.position_size_mode === "pct_available") {
    return { base: portfolio.available, slots: 1 };
  }
  return { base: 0, slots: 1 };
}

export function explainOrderSize(
  config: AppConfig,
  portfolio: Portfolio,
): OrderSizeDetail {
  const mode = config.position_size_mode || "fixed";
  const pct = config.order_size_pct ?? 2;
  const cap = config.max_order_size_usdt ?? 0;
  const minSz = config.min_order_size_usdt ?? 10;
  const basis = config.order_size_basis || "notional";
  const lev = Math.max(1, config.leverage || 1);
  const open = portfolio.positions.length;
  const split = !!config.size_split_slots;
  const steps: string[] = [];

  let notional: number;

  if (mode === "fixed") {
    notional = config.order_size_usdt;
    steps.push(`고정 주문 명목 $${notional.toLocaleString()}`);
  } else {
    const { base, slots } = slotBase(config, portfolio);
    if (split && config.max_positions > 0) {
      const src = mode === "pct_equity" ? "총자산" : "가용";
      const amt = mode === "pct_equity" ? portfolio.equity : portfolio.available;
      steps.push(
        `${src} $${amt.toLocaleString()} ÷ 남은슬롯 ${slots}개 = $${Math.round(base).toLocaleString()}/슬롯`,
      );
    } else {
      const src = mode === "pct_equity" ? "총자산(Equity)" : "가용 잔고";
      steps.push(`${src} $${Math.round(base).toLocaleString()}`);
    }

    if (basis === "margin") {
      const marginRaw = base * (pct / 100);
      notional = marginRaw * lev;
      steps.push(`× ${pct}% = 증거금 $${Math.round(marginRaw).toLocaleString()}`);
      steps.push(`× 레버 ${lev}x = 명목(포지션) $${Math.round(notional).toLocaleString()}`);
    } else {
      notional = base * (pct / 100);
      steps.push(`× ${pct}% = 명목(포지션) $${Math.round(notional).toLocaleString()}`);
      steps.push(`÷ 레버 ${lev}x = 증거금 $${Math.round(notional / lev).toLocaleString()}`);
    }
  }

  notional = Math.max(minSz, notional);
  if (cap > 0) notional = Math.min(cap, notional);
  notional = Math.round(notional * 100) / 100;
  const margin = Math.round((notional / lev) * 100) / 100;
  const { slots } = slotBase(config, portfolio);

  const basisLabel = basis === "margin" ? "증거금 %" : "명목(포지션) %";
  const splitNote =
    split && slots > 1 ? `, 슬롯당 ${pct}%` : `, ${pct}%`;

  return {
    notionalUsdt: notional,
    marginUsdt: margin,
    leverage: lev,
    baseUsdt: slotBase(config, portfolio).base,
    pct,
    slotsRemaining: slots,
    openPositions: open,
    steps,
    summary: `명목 $${notional.toLocaleString()} · 증거금 $${margin.toLocaleString()} (${basisLabel}${splitNote}, 레버 ${lev}x)`,
  };
}

export function previewOrderSizeUsdt(
  config: AppConfig,
  portfolio: Portfolio,
): number {
  return explainOrderSize(config, portfolio).notionalUsdt;
}

export function positionSizeModeLabel(mode?: string): string {
  if (mode === "pct_available") return "가용 잔고 %";
  if (mode === "pct_equity") return "총자산(Equity) %";
  return "고정 USD";
}

export function orderSizeBasisLabel(basis?: string): string {
  return basis === "margin" ? "증거금 %" : "명목(포지션) %";
}

export function marginModeLabel(mode?: string): string {
  return mode === "cross" ? "교차 (Cross)" : "격리 (Isolated)";
}

/** Human-readable preset for “X% of real balance per entry”. */
export function describeBalancePctEntry(
  config: AppConfig,
  portfolio: Portfolio,
): { title: string; lines: string[] } {
  const pct = config.order_size_pct ?? 20;
  const lev = Math.max(1, config.leverage || 1);
  const basis = config.order_size_basis || "notional";
  const mode = config.position_size_mode || "fixed";
  const equity = portfolio.equity;
  const available = portfolio.available;

  if (mode === "fixed") {
    return {
      title: "고정 USD 모드",
      lines: [`매 진입 명목 $${config.order_size_usdt} (잔고 %와 무관)`],
    };
  }

  const baseLabel =
    mode === "pct_equity" ? "총자산(Equity)" : "가용 잔고";
  const baseAmt = mode === "pct_equity" ? equity : available;

  if (basis === "margin") {
    const margin = baseAmt * (pct / 100);
    const notional = margin * lev;
    return {
      title: `${baseLabel}의 ${pct}% → 증거금 (레버 ${lev}x)`,
      lines: [
        `${baseLabel} $${Math.round(baseAmt).toLocaleString()} × ${pct}% = 증거금 $${Math.round(margin).toLocaleString()}`,
        `× 레버 ${lev}x = 포지션(명목) $${Math.round(notional).toLocaleString()}`,
      ],
    };
  }

  const notional = baseAmt * (pct / 100);
  const margin = notional / lev;
  return {
    title: `${baseLabel}의 ${pct}% → 포지션(명목)`,
    lines: [
      `${baseLabel} $${Math.round(baseAmt).toLocaleString()} × ${pct}% = 명목 $${Math.round(notional).toLocaleString()}`,
      `÷ 레버 ${lev}x = 증거금 $${Math.round(margin).toLocaleString()}`,
    ],
  };
}
