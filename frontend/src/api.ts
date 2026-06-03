import type { AppConfig, StatusData } from "./types";

const BASE = "";

export async function fetchStatus(): Promise<StatusData> {
  const res = await fetch(`${BASE}/api/status`);
  return res.json();
}

export async function startBot(
  autoInvest = true,
  strategy?: string,
  positionSide = "auto",
) {
  const res = await fetch(`${BASE}/api/bot/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auto_invest: autoInvest,
      strategy_mode: strategy,
      position_side: positionSide,
    }),
  });
  return res.json();
}

export async function stopBot() {
  const res = await fetch(`${BASE}/api/bot/stop`, { method: "POST" });
  return res.json();
}

export async function scanNow() {
  const res = await fetch(`${BASE}/api/scan`, { method: "POST" });
  return res.json();
}

export async function updateConfig(
  config: AppConfig,
): Promise<{ ok: boolean; message?: string; api_keys_configured?: boolean }> {
  const res = await fetch(`${BASE}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  return res.json();
}

export async function setPositionSlTp(
  instId: string,
  slPct: number,
  tpPct: number,
): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${BASE}/api/position/sl-tp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inst_id: instId, sl_pct: slPct, tp_pct: tpPct }),
  });
  return res.json();
}

export async function resetPositionSlTpAuto(
  instId: string,
): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${BASE}/api/position/sl-tp/auto`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inst_id: instId }),
  });
  return res.json();
}

export async function runBacktest(body: {
  symbols?: string[];
  candle_limit?: number;
  optimize?: boolean;
}): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${BASE}/api/backtest/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function fetchBacktestStatus(): Promise<{
  status: import("./types").BacktestStatus;
  result: import("./types").BacktestResult | null;
}> {
  const res = await fetch(`${BASE}/api/backtest/status`);
  return res.json();
}

export async function applyBacktest(): Promise<{
  ok: boolean;
  message?: string;
  min_score?: number;
}> {
  const res = await fetch(`${BASE}/api/backtest/apply`, { method: "POST" });
  return res.json();
}

export async function closePosition(instId: string) {
  const res = await fetch(`${BASE}/api/order/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inst_id: instId }),
  });
  return res.json();
}

export async function closeAll() {
  const res = await fetch(`${BASE}/api/order/close-all`, { method: "POST" });
  return res.json();
}

export async function fetchCandles(instId: string, strategy: string, side = "long") {
  const q = new URLSearchParams({ inst_id: instId, strategy, side });
  const res = await fetch(`${BASE}/api/candles?${q}`);
  return res.json() as Promise<{
    candles: { time: number; open: number; high: number; low: number; close: number; volume?: number }[];
    sl_pct: number;
    tp_pct: number;
    sl_tp_method?: string;
  }>;
}

export async function resetPaper(initialBalance?: number) {
  const res = await fetch(`${BASE}/api/paper/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      initial_balance: initialBalance,
    }),
  });
  return res.json() as Promise<{
    ok: boolean;
    message: string;
    balance?: number;
    equity?: number;
  }>;
}

export async function testConnection() {
  const res = await fetch(`${BASE}/api/test-connection`, { method: "POST" });
  return res.json();
}

export async function setTradeMode(mode: string) {
  const res = await fetch(`${BASE}/api/trade-mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  return res.json();
}

export async function setStrategy(strategy: string) {
  const res = await fetch(`${BASE}/api/strategy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy }),
  });
  return res.json();
}

export async function setPositionSide(mode: string) {
  const res = await fetch(`${BASE}/api/position-side`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  return res.json();
}

export async function manualOrder(
  instId: string,
  side: "long" | "short",
  sizeUsdt: number,
  leverage: number,
) {
  const res = await fetch(`${BASE}/api/order/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      inst_id: instId,
      side,
      size_usdt: sizeUsdt,
      leverage,
    }),
  });
  return res.json();
}

export function connectWS(onMessage: (data: StatusData) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch { /* ignore */ }
  };
  return ws;
}
