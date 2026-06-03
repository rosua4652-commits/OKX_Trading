import type { Portfolio, Position } from "./types";

export interface AllocationSlice {
  key: string;
  label: string;
  instId?: string;
  margin: number;
  notional: number;
  pct: number;
  color: string;
  side?: string;
  unrealizedPnl?: number;
}

const SLICE_COLORS = [
  "#58a6ff",
  "#3fb950",
  "#d29922",
  "#bc8cff",
  "#f85149",
  "#79c0ff",
  "#ffa657",
  "#56d364",
];

export function coinLabel(instId: string): string {
  return instId.replace(/-USDT-SWAP$/i, "").replace(/-USDT$/i, "");
}

export function positionNotional(p: Position): number {
  if (p.notional_usdt && p.notional_usdt > 0) return p.notional_usdt;
  const px = p.current_price > 0 ? p.current_price : p.entry_price;
  return px * p.quantity;
}

export function positionMargin(p: Position, defaultLeverage: number): number {
  const notional = positionNotional(p);
  if (p.instrument_type === "spot") return notional;
  const lev = p.leverage && p.leverage > 0 ? p.leverage : defaultLeverage;
  return notional / Math.max(1, lev);
}

export function computeAllocation(
  portfolio: Portfolio,
  defaultLeverage: number,
): {
  slices: AllocationSlice[];
  deployed: number;
  available: number;
  equity: number;
  unrealizedPnl: number;
} {
  const positionSlices: AllocationSlice[] = portfolio.positions.map((p, i) => {
    const notional = positionNotional(p);
    const margin = positionMargin(p, defaultLeverage);
    return {
      key: p.inst_id,
      label: coinLabel(p.inst_id),
      instId: p.inst_id,
      margin,
      notional,
      pct: 0,
      color: SLICE_COLORS[i % SLICE_COLORS.length],
      side: p.side,
      unrealizedPnl: p.unrealized_pnl,
    };
  });

  const deployed = positionSlices.reduce((s, x) => s + x.margin, 0);
  const available = Math.max(0, portfolio.available);
  const unrealizedPnl = portfolio.unrealized_pnl;
  const baseTotal = deployed + available;
  const equity = portfolio.equity > 0 ? portfolio.equity : baseTotal + unrealizedPnl;

  const slices: AllocationSlice[] = [
    ...positionSlices.sort((a, b) => b.margin - a.margin),
    {
      key: "available",
      label: "가용 USD",
      margin: available,
      notional: available,
      pct: 0,
      color: "#484f58",
    },
  ];

  const denom = baseTotal > 0 ? baseTotal : equity;
  for (const s of slices) {
    s.pct = denom > 0 ? (s.margin / denom) * 100 : 0;
  }

  return {
    slices: slices.filter((s) => s.margin > 0.01 || s.key === "available"),
    deployed,
    available,
    equity,
    unrealizedPnl,
  };
}

export function pieArcs(
  slices: AllocationSlice[],
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
): { d: string; color: string; key: string; pct: number }[] {
  const visible = slices.filter((s) => s.pct >= 0.05);
  if (visible.length === 0) return [];

  let angle = -Math.PI / 2;
  const out: { d: string; color: string; key: string; pct: number }[] = [];

  for (const s of visible) {
    const sweep = (s.pct / 100) * Math.PI * 2;
    if (sweep < 0.0001) continue;
    const a0 = angle;
    const a1 = angle + sweep;
    const x0o = cx + outerR * Math.cos(a0);
    const y0o = cy + outerR * Math.sin(a0);
    const x1o = cx + outerR * Math.cos(a1);
    const y1o = cy + outerR * Math.sin(a1);
    const x0i = cx + innerR * Math.cos(a1);
    const y0i = cy + innerR * Math.sin(a1);
    const x1i = cx + innerR * Math.cos(a0);
    const y1i = cy + innerR * Math.sin(a0);
    const large = sweep > Math.PI ? 1 : 0;
    const d = [
      `M ${x0o} ${y0o}`,
      `A ${outerR} ${outerR} 0 ${large} 1 ${x1o} ${y1o}`,
      `L ${x0i} ${y0i}`,
      `A ${innerR} ${innerR} 0 ${large} 0 ${x1i} ${y1i}`,
      "Z",
    ].join(" ");
    out.push({ d, color: s.color, key: s.key, pct: s.pct });
    angle = a1;
  }
  return out;
}
