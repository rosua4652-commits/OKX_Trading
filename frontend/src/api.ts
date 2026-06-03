import type { AppConfig, StatusData } from "./types";

const BASE = "";

export async function fetchStatus(): Promise<StatusData> {
  const res = await fetch(`${BASE}/api/status`);
  return res.json();
}

export async function startBot(autoInvest = true, strategy?: string) {
  const res = await fetch(`${BASE}/api/bot/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_invest: autoInvest, strategy_mode: strategy }),
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

export async function updateConfig(config: AppConfig) {
  const res = await fetch(`${BASE}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
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
