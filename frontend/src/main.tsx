import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  closeAll,
  closePosition,
  connectWS,
  fetchStatus,
  scanNow,
  setStrategy,
  setTradeMode,
  startBot,
  stopBot,
  testConnection,
  updateConfig,
} from "./api";
import type { AppConfig, StatusData } from "./types";
import "./index.css";

function fmt(n: number, digits = 2) {
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function App() {
  const [data, setData] = useState<StatusData | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);

  const refresh = useCallback(async () => {
    const s = await fetchStatus();
    setData(s);
    setConfig(s.config);
  }, []);

  useEffect(() => {
    refresh();
    const ws = connectWS((d) => {
      setData(d);
      setConfig(d.config);
    });
    const iv = setInterval(refresh, 10000);
    return () => { ws.close(); clearInterval(iv); };
  }, [refresh]);

  if (!data || !config) return <div className="app">Loading...</div>;

  const { portfolio, bot, candidates } = data;
  const running = bot.status.running;

  const handleSaveConfig = async () => {
    await updateConfig(config);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <h1>OKX Auto Trader</h1>
          <span className="build">build {data.build}</span>
        </div>
        <div className="controls">
          <button
            className={config.trade_mode === "paper" ? "active" : ""}
            onClick={() => { setTradeMode("paper"); setConfig({ ...config, trade_mode: "paper" }); }}
          >
            모의투자
          </button>
          <button
            className={config.trade_mode === "live" ? "active" : ""}
            onClick={() => { setTradeMode("live"); setConfig({ ...config, trade_mode: "live" }); }}
          >
            실거래
          </button>
          <button
            className={config.strategy_mode === "scalp" ? "active" : ""}
            onClick={() => { setStrategy("scalp"); setConfig({ ...config, strategy_mode: "scalp" }); }}
          >
            단타
          </button>
          <button
            className={config.strategy_mode === "swing" ? "active" : ""}
            onClick={() => { setStrategy("swing"); setConfig({ ...config, strategy_mode: "swing" }); }}
          >
            장타
          </button>
          {!running ? (
            <button className="primary" onClick={() => startBot(true, config.strategy_mode)}>
              봇 시작
            </button>
          ) : (
            <button className="danger" onClick={() => stopBot()}>
              봇 중지
            </button>
          )}
          <button onClick={() => scanNow().then(refresh)}>스캔</button>
          <button onClick={() => closeAll().then(refresh)}>전량 청산</button>
        </div>
      </header>

      <div className="grid">
        <div className="card">
          <h3>자산 (Equity)</h3>
          <div className="value">${fmt(portfolio.equity)}</div>
        </div>
        <div className="card">
          <h3>가용 잔고</h3>
          <div className="value">${fmt(portfolio.available)}</div>
        </div>
        <div className="card">
          <h3>미실현 PnL</h3>
          <div className={`value ${portfolio.unrealized_pnl >= 0 ? "positive" : "negative"}`}>
            {portfolio.unrealized_pnl >= 0 ? "+" : ""}{fmt(portfolio.unrealized_pnl)}
          </div>
        </div>
        <div className="card">
          <h3>실현 PnL / 승률</h3>
          <div className={`value ${portfolio.realized_pnl >= 0 ? "positive" : "negative"}`}>
            {portfolio.realized_pnl >= 0 ? "+" : ""}{fmt(portfolio.realized_pnl)}
          </div>
          <div style={{ fontSize: "0.875rem", color: "#8b949e", marginTop: 4 }}>
            {portfolio.trade_count}건 / 승률 {portfolio.win_rate}%
          </div>
        </div>
        <div className="card">
          <h3>봇 상태</h3>
          <div>
            <span className={`badge ${running ? "running" : "stopped"}`}>
              {running ? "RUNNING" : "STOPPED"}
            </span>
            <span style={{ marginLeft: 8, fontSize: "0.875rem" }}>
              {bot.status.phase} | 스캔 #{bot.status.scan_count}
            </span>
          </div>
        </div>
        <div className="card">
          <h3>연결</h3>
          <div className="value" style={{ fontSize: "1rem" }}>
            {data.linked ? "OKX 연결됨" : data.link_message || "미연결"}
          </div>
          <button style={{ marginTop: 8 }} onClick={() => testConnection().then(refresh)}>
            연결 테스트
          </button>
        </div>
      </div>

      <div className="section">
        <h2>보유 포지션 ({portfolio.positions.length})</h2>
        {portfolio.positions.length === 0 ? (
          <p style={{ color: "#8b949e" }}>포지션 없음</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>종목</th>
                <th>방향</th>
                <th>수량</th>
                <th>진입가</th>
                <th>현재가</th>
                <th>PnL</th>
                <th>SL / TP</th>
                <th>전략</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.id}>
                  <td>{p.inst_id}</td>
                  <td><span className={`badge ${p.side}`}>{p.side.toUpperCase()}</span></td>
                  <td>{fmt(p.quantity, 4)}</td>
                  <td>{fmt(p.entry_price)}</td>
                  <td>{fmt(p.current_price)}</td>
                  <td className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>
                    {p.unrealized_pnl >= 0 ? "+" : ""}{fmt(p.unrealized_pnl)} ({fmt(p.unrealized_pnl_pct, 1)}%)
                  </td>
                  <td>{fmt(p.stop_loss)} / {fmt(p.take_profit)}</td>
                  <td>{p.strategy_mode}</td>
                  <td>
                    <button onClick={() => closePosition(p.inst_id).then(refresh)}>청산</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="section">
        <h2>매매 후보 (AI 분석)</h2>
        {candidates.length === 0 ? (
          <p style={{ color: "#8b949e" }}>스캔 버튼을 눌러 분석하세요</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>종목</th>
                <th>가격</th>
                <th>24h</th>
                <th>거래량</th>
                <th>RSI</th>
                <th>추세</th>
                <th>점수</th>
                <th>판단</th>
                <th>근거</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.inst_id}>
                  <td>{c.inst_id}</td>
                  <td>${fmt(c.last_price)}</td>
                  <td className={c.change_24h_pct >= 0 ? "positive" : "negative"}>
                    {c.change_24h_pct >= 0 ? "+" : ""}{fmt(c.change_24h_pct, 1)}%
                  </td>
                  <td>${(c.volume_24h_usdt / 1e6).toFixed(1)}M</td>
                  <td>{fmt(c.rsi, 0)}</td>
                  <td>{c.trend}</td>
                  <td>
                    <strong>{fmt(c.score, 0)}</strong>
                    <div className="score-bar"><div className="fill" style={{ width: `${Math.min(c.score, 100)}%` }} /></div>
                  </td>
                  <td>{c.outlook} {c.scalp_ok ? "✓단타" : ""} {c.swing_ok ? "✓장타" : ""}</td>
                  <td style={{ fontSize: "0.75rem", color: "#8b949e" }}>{c.reasons.slice(0, 3).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="section">
        <h2>설정</h2>
        <div className="settings-row">
          <label>상품 유형</label>
          <select
            value={config.instrument_type}
            onChange={(e) => setConfig({ ...config, instrument_type: e.target.value })}
          >
            <option value="swap">선물 (SWAP)</option>
            <option value="spot">현물 (SPOT)</option>
            <option value="futures">선물 (FUTURES)</option>
          </select>
        </div>
        <div className="settings-row">
          <label>주문 크기 (USDT)</label>
          <input type="number" value={config.order_size_usdt}
            onChange={(e) => setConfig({ ...config, order_size_usdt: +e.target.value })} />
        </div>
        <div className="settings-row">
          <label>레버리지</label>
          <input type="number" value={config.leverage}
            onChange={(e) => setConfig({ ...config, leverage: +e.target.value })} />
        </div>
        <div className="settings-row">
          <label>손절 %</label>
          <input type="number" step="0.1" value={config.stop_loss_pct}
            onChange={(e) => setConfig({ ...config, stop_loss_pct: +e.target.value })} />
        </div>
        <div className="settings-row">
          <label>익절 %</label>
          <input type="number" step="0.1" value={config.take_profit_pct}
            onChange={(e) => setConfig({ ...config, take_profit_pct: +e.target.value })} />
        </div>
        <div className="settings-row">
          <label>최대 포지션</label>
          <input type="number" value={config.max_positions}
            onChange={(e) => setConfig({ ...config, max_positions: +e.target.value })} />
        </div>
        <div className="settings-row">
          <label>최소 점수</label>
          <input type="number" value={config.min_score}
            onChange={(e) => setConfig({ ...config, min_score: +e.target.value })} />
        </div>
        <div className="settings-row">
          <label>API Key</label>
          <input type="password" value={config.okx_api_key}
            onChange={(e) => setConfig({ ...config, okx_api_key: e.target.value })} />
        </div>
        <div className="settings-row">
          <label>API Secret</label>
          <input type="password" value={config.okx_api_secret}
            onChange={(e) => setConfig({ ...config, okx_api_secret: e.target.value })} />
        </div>
        <div className="settings-row">
          <label>Passphrase</label>
          <input type="password" value={config.okx_passphrase}
            onChange={(e) => setConfig({ ...config, okx_passphrase: e.target.value })} />
        </div>
        <div className="settings-row">
          <label>데모 모드</label>
          <select value={config.okx_flag}
            onChange={(e) => setConfig({ ...config, okx_flag: e.target.value })}>
            <option value="1">데모 (테스트)</option>
            <option value="0">실거래</option>
          </select>
        </div>
        <button className="primary" onClick={handleSaveConfig} style={{ marginTop: 12 }}>
          설정 저장
        </button>
      </div>

      <div className="section">
        <h2>활동 로그</h2>
        {bot.activity_log.slice(0, 20).map((log, i) => (
          <div key={i} className={`log-entry ${log.level}`}>
            <span className="ts">{log.ts?.slice(11, 19)}</span>
            [{log.phase}] {log.message}
          </div>
        ))}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>
);
