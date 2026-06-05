import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  closeAll,
  closePosition,
  connectWS,
  fetchStatus,
  fetchTrades,
  manualOrder,
  resetPaper,
  scanNow,
  setPositionSide,
  setStrategy,
  setTradeMode,
  startBot,
  stopBot,
  testConnection,
  updateConfig,
} from "./api";
import { CandleChart, MiniCandles } from "./CandleChart";
import {
  buildCandidateChartTarget,
  buildPositionChartTarget,
  ChartModal,
  type ChartViewTarget,
} from "./ChartModal";
import { fmtNum, fmtPnlUsdt, fmtPrice, fmtUsd, fmtVolumeUsdt } from "./format";
import { describeBalancePctEntry, explainOrderSize, marginModeLabel, orderSizeBasisLabel, positionSizeModeLabel } from "./orderSize";
import {
  chartStrategyKey,
  scalpEnabled,
  slTpPctForStrategy,
  strategyModesFromToggle,
  swingEnabled,
} from "./strategy";
import { BacktestPanel } from "./BacktestPanel";
import { AssetAllocationPanel } from "./AssetAllocation";
import { PositionSlTpEditor } from "./PositionSlTpEditor";
import { RsiGauge } from "./Sparkline";
import type { AppConfig, CoinCandidate, Position, StatusData, TradeRecord } from "./types";
import "./index.css";

function App() {
  const [data, setData] = useState<StatusData | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [apiDraft, setApiDraft] = useState({ key: "", secret: "", pass: "" });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expandedCandidateId, setExpandedCandidateId] = useState<string | null>(null);
  const [chartTarget, setChartTarget] = useState<ChartViewTarget | null>(null);
  const [configSaveStatus, setConfigSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [mainTab, setMainTab] = useState<"trade" | "exits" | "backtest">("trade");
  const [exitFilter, setExitFilter] = useState<"all" | "sl" | "tp" | "other">("all");
  const configLockedRef = useRef(false);
  const refreshInFlightRef = useRef(false);

  const lockConfigEdits = () => {
    configLockedRef.current = true;
  };

  const applyServerState = useCallback((s: StatusData) => {
    setData(s);
    if (configLockedRef.current) return;

    setConfig((prev) => {
      const next = { ...s.config };
      if (!prev) return next;
      const editingApi =
        apiDraft.key !== "" || apiDraft.secret !== "" || apiDraft.pass !== "";
      if (editingApi) {
        next.okx_api_key = apiDraft.key;
        next.okx_api_secret = apiDraft.secret;
        next.okx_passphrase = apiDraft.pass;
      }
      return next;
    });
  }, [apiDraft]);

  const refresh = useCallback(async () => {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;
    try {
      const s = await fetchStatus();
      applyServerState(s);
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [applyServerState]);

  useEffect(() => {
    refresh();
    const ws = connectWS((d) => applyServerState(d));
    const iv = setInterval(refresh, 3000);
    return () => { ws.close(); clearInterval(iv); };
  }, [refresh, applyServerState]);

  useEffect(() => {
    if (mainTab !== "exits") return;
    let cancelled = false;
    fetchTrades()
      .then((res) => {
        if (cancelled) return;
        setData((prev) => (prev ? { ...prev, trades: res.trades ?? [] } : prev));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [mainTab]);

  if (!data || !config) return <div className="app">Loading...</div>;

  const { portfolio, bot, candidates } = data;
  const decisionLogs = bot.activity_log.filter((log) => log.phase === "decision");
  const running = bot.status.running;
  const nextOrderDetailRaw = data.next_order_size_detail;
  const nextOrderComputed = explainOrderSize(config, portfolio);
  const nextOrderUsdt =
    data.next_order_size_usdt ?? nextOrderComputed.notionalUsdt;
  const nextOrderMargin =
    nextOrderDetailRaw?.margin_usdt ?? nextOrderComputed.marginUsdt;
  const nextOrderSteps =
    nextOrderDetailRaw?.steps ?? nextOrderComputed.steps;
  const balancePctGuide = describeBalancePctEntry(config, portfolio);

  const isPaper = config.trade_mode === "paper";
  const moneyTag = isPaper ? "USD · 모의" : "USD";

  const liqRisk = (p: Position) => {
    const liq = p.liquidation_price ?? 0;
    if (!liq || !p.current_price || !p.stop_loss) return null;
    const current = p.current_price;
    const sl = p.stop_loss;
    if (p.side === "long") {
      const denom = current - liq;
      if (denom <= 0) return "위험";
      return (current - sl) / denom < 0.25 ? "청산가 근접" : null;
    }
    const denom = liq - current;
    if (denom <= 0) return "위험";
    return (sl - current) / denom < 0.25 ? "청산가 근접" : null;
  };

  const patchConfig = (patch: Partial<AppConfig>) => {
    lockConfigEdits();
    setConfig((c) => (c ? { ...c, ...patch } : c));
  };

  const handleSaveConfig = async () => {
    setConfigSaveStatus("saving");
    const payload: AppConfig = {
      ...config,
      okx_api_key: apiDraft.key,
      okx_api_secret: apiDraft.secret,
      okx_passphrase: apiDraft.pass,
    };
    try {
      const res = await updateConfig(payload);
      setApiDraft({ key: "", secret: "", pass: "" });
      configLockedRef.current = false;
      if (res?.config) {
        setConfig(res.config);
      }
      setConfigSaveStatus(res?.ok === false ? "error" : "saved");
      if (res?.ok !== false) {
        window.setTimeout(() => setConfigSaveStatus("idle"), 4000);
      }
      window.setTimeout(() => refresh().catch(() => undefined), 500);
    } catch {
      configLockedRef.current = false;
      setConfigSaveStatus("error");
    }
  };

  const toggleSettings = () => {
    if (settingsOpen) {
      configLockedRef.current = false;
      setSettingsOpen(false);
      refresh();
      return;
    }
    lockConfigEdits();
    setSettingsOpen(true);
  };

  const applyStrategyToggles = (scalp: boolean, swing: boolean) => {
    const mode = strategyModesFromToggle(scalp, swing);
    if (!mode) return;
    setStrategy(mode);
    patchConfig({ strategy_mode: mode });
  };

  const openPositionChart = (p: Position) => {
    setChartTarget(
      buildPositionChartTarget(p, chartStrategyKey(config.strategy_mode, p.strategy_mode)),
    );
  };

  const openCandidateChart = (c: CoinCandidate) => {
    const chartStrat =
      config.strategy_mode === "both"
        ? (c.swing_ok && !c.scalp_ok ? "swing" : "scalp")
        : chartStrategyKey(config.strategy_mode);
    const pct = slTpPctForStrategy(chartStrat);
    setChartTarget(
      buildCandidateChartTarget(c.inst_id, chartStrat, {
        slPct: pct.sl,
        tpPct: pct.tp,
        side: c.outlook === "short" ? "short" : "long",
      }),
    );
  };

  return (
    <div className="app">
      <ChartModal
        target={chartTarget}
        onClose={() => setChartTarget(null)}
        configLeverage={config.leverage}
      />
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
            className={scalpEnabled(config.strategy_mode) ? "active" : ""}
            title="단타 전략 (5분봉·짧은 SL/TP)"
            onClick={() =>
              applyStrategyToggles(
                !scalpEnabled(config.strategy_mode),
                swingEnabled(config.strategy_mode),
              )
            }
          >
            단타
          </button>
          <button
            className={swingEnabled(config.strategy_mode) ? "active" : ""}
            title="장타 전략 (1시간봉·넓은 SL/TP)"
            onClick={() =>
              applyStrategyToggles(
                scalpEnabled(config.strategy_mode),
                !swingEnabled(config.strategy_mode),
              )
            }
          >
            장타
          </button>
          {config.strategy_mode === "both" && (
            <span className="strategy-both-hint">동시</span>
          )}
          <span className="control-divider" />
          <button
            className={config.position_side === "auto" ? "active" : ""}
            onClick={() => { setPositionSide("auto"); setConfig({ ...config, position_side: "auto" }); }}
            title="상승 예상→롱, 하락·고점 예상→숏 (AI 판단)"
          >
            자동 롱/숏
          </button>
          <button
            className={`long ${config.position_side === "long" ? "active" : ""}`}
            onClick={() => { setPositionSide("long"); setConfig({ ...config, position_side: "long" }); }}
            title="올라갈 때 수익 (상승 베팅)"
          >
            롱만
          </button>
          <button
            className={`short ${config.position_side === "short" ? "active" : ""}`}
            onClick={() => { setPositionSide("short"); setConfig({ ...config, position_side: "short" }); }}
            title="떨어질 때 수익 (고점·하락 베팅, 선물/SWAP)"
          >
            숏만
          </button>
          {!running ? (
            <>
              <button
                className="primary"
                title="차트 AI 분석 후 롱/숏 자동 진입"
                onClick={async () => {
                  await setPositionSide("auto");
                  setConfig({ ...config, position_side: "auto", auto_invest: true });
                  await startBot(true, config.strategy_mode, "auto");
                  refresh();
                }}
              >
                자동매매 시작
              </button>
              <button onClick={() => startBot(true, config.strategy_mode, config.position_side)}>
                봇만 시작
              </button>
            </>
          ) : (
            <button className="danger" onClick={() => stopBot()}>
              봇 중지
            </button>
          )}
          <button onClick={() => scanNow().then(refresh)}>스캔</button>
          <button onClick={() => closeAll().then(refresh)}>전량 청산</button>
          <span className="control-divider" />
          <button
            className={`settings-toggle ${settingsOpen ? "active" : ""}`}
            onClick={toggleSettings}
          >
            설정 {settingsOpen ? "▲" : "▼"}
          </button>
          {config.trade_mode === "paper" && (
            <>
              <label className="paper-balance-input">
                초기자금 $
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={config.paper_initial_balance ?? 10000}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    if (!Number.isFinite(n) || n <= 0) return;
                    patchConfig({ paper_initial_balance: n });
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              </label>
              <button
                className="reset-paper"
                onClick={async () => {
                  const bal = config.paper_initial_balance ?? 10000;
                  if (
                    !confirm(
                      `모의투자를 $${bal.toLocaleString()} 로 초기화할까요?\n(포지션·거래기록 삭제, 봇 자동 중지)`,
                    )
                  ) {
                    return;
                  }
                  await updateConfig(config);
                  const r = await resetPaper(bal);
                  if (!r.ok) {
                    alert(r.message || "초기화 실패");
                  } else {
                    alert(r.message);
                  }
                  refresh();
                }}
              >
                모의투자 초기화
              </button>
            </>
          )}
        </div>
      </header>

      <nav className="app-tabs">
        <button
          type="button"
          className={mainTab === "trade" ? "active" : ""}
          onClick={() => setMainTab("trade")}
        >
          매매 · 포지션
        </button>
        <button
          type="button"
          className={mainTab === "exits" ? "active" : ""}
          onClick={() => setMainTab("exits")}
        >
          익/손절 내역
          {(data.trades?.length ?? 0) > 0 && (
            <span className="tab-count">{data.trades?.length}</span>
          )}
        </button>
        <button
          type="button"
          className={mainTab === "backtest" ? "active" : ""}
          onClick={() => setMainTab("backtest")}
        >
          백테스트
          {data.backtest?.status?.running && (
            <span className="tab-count">…</span>
          )}
        </button>
      </nav>

      {settingsOpen && (
        <div className="settings-panel">
          <h2>설정 <span style={{ fontSize: "0.75rem", color: "#d29922" }}>편집 중 — 자동 새로고침 일시 중지</span></h2>
          <div className="settings-grid">
            <div className="settings-row">
              <label>상품 유형</label>
              <select
                value={config.instrument_type}
                onChange={(e) => patchConfig({ instrument_type: e.target.value })}
              >
                <option value="swap">선물 (SWAP)</option>
                <option value="spot">현물 (SPOT)</option>
                <option value="futures">선물 (FUTURES)</option>
              </select>
            </div>
            <div className="settings-row">
              <label>모의투자 초기 자금 (USD, 제한 없음)</label>
              <input
                type="number"
                min={1}
                step={1}
                value={config.paper_initial_balance ?? 10000}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (!Number.isFinite(n) || n <= 0) return;
                  patchConfig({ paper_initial_balance: n });
                }}
              />
              <p className="settings-hint" style={{ gridColumn: "1 / -1", fontSize: "0.75rem" }}>
                100만·1000만 등 원하는 금액 입력 후 「설정 저장」→「모의투자 초기화」로 반영.
                USDT-M 선물과 동일하게 1 USD ≈ 1 USDT로 계산합니다.
              </p>
            </div>
            <div className="settings-row">
              <label>주문 크기 방식</label>
              <select
                value={config.position_size_mode || "fixed"}
                onChange={(e) => patchConfig({ position_size_mode: e.target.value })}
              >
                <option value="fixed">고정 USD</option>
                <option value="pct_available">가용 잔고 %</option>
                <option value="pct_equity">총자산(Equity) %</option>
              </select>
            </div>
            {(config.position_size_mode || "fixed") === "fixed" ? (
              <div className="settings-row">
                <label>주문 금액 (USD)</label>
                <input
                  type="number"
                  value={config.order_size_usdt}
                  onChange={(e) => patchConfig({ order_size_usdt: Number(e.target.value) })}
                />
              </div>
            ) : (
              <>
                <div className="settings-row">
                  <label>비율 (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    min={0.1}
                    value={config.order_size_pct ?? 2}
                    onChange={(e) => patchConfig({ order_size_pct: Number(e.target.value) })}
                  />
                </div>
                <div className="settings-row">
                  <label>비율 기준</label>
                  <select
                    value={config.order_size_basis || "notional"}
                    onChange={(e) => patchConfig({ order_size_basis: e.target.value })}
                    title="명목=포지션 크기(USD), 증거금=실제 묶이는 USD"
                  >
                    <option value="notional">명목(포지션 크기) %</option>
                    <option value="margin">증거금 %</option>
                  </select>
                </div>
                <div className="settings-row">
                  <label title="남은 포지션 슬롯으로 나눈 뒤 % 적용 (전체 30%와 다름)">
                    잔고÷남은슬롯 후 %
                  </label>
                  <input
                    type="checkbox"
                    checked={!!config.size_split_slots}
                    onChange={(e) => patchConfig({ size_split_slots: e.target.checked })}
                  />
                </div>
              </>
            )}
            <div className="settings-row">
              <label>주문 상한 (USD, 0=무제한)</label>
              <input
                type="number"
                min={0}
                value={config.max_order_size_usdt ?? 0}
                onChange={(e) => patchConfig({ max_order_size_usdt: Number(e.target.value) })}
              />
            </div>
            <div className="order-size-breakdown">
              <p className="settings-hint order-size-preview">
                다음 진입: <strong>명목 ${nextOrderUsdt.toLocaleString()}</strong>
                {" · "}
                <strong>증거금 ${Math.round(nextOrderMargin).toLocaleString()}</strong>
                {" "}
                (레버 {config.leverage}x · {marginModeLabel(config.margin_mode)})
              </p>
              <ol className="order-size-steps">
                {nextOrderSteps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
              {config.size_split_slots && (
                <p className="order-size-note">
                  「잔고÷남은슬롯」이 켜져 있으면 <strong>전체 자금의 {config.order_size_pct}%가 아니라</strong>,
                  남은 슬롯 1개분에 {config.order_size_pct}%가 적용됩니다.
                  전체 가용의 {config.order_size_pct}%를 쓰려면 이 체크를 끄세요.
                </p>
              )}
              {config.order_size_basis === "margin" ? (
                <p className="order-size-note">
                  비율 기준=증거금 % →{" "}
                  {config.position_size_mode === "pct_equity" ? "총자산" : "가용"}×
                  {config.order_size_pct}%가 증거금, ×레버가 명목입니다.
                </p>
              ) : (
                <p className="order-size-note">
                  비율 기준=명목 % →{" "}
                  {config.position_size_mode === "pct_equity" ? "총자산" : "가용"}×
                  {config.order_size_pct}%가 포지션 크기, ÷레버가 증거금입니다.
                </p>
              )}
              <div className="order-size-preset-box">
                <strong>📱 OKX 주문창 Amount % 슬라이더와 동일하게</strong>
                <p className="order-size-preset-desc">
                  OKX: 가용(Available) × % = 증거금(Cost) → × 레버 = Max buy(명목)
                </p>
                <button
                  type="button"
                  className="preset-link preset-link-block"
                  onClick={() =>
                    patchConfig({
                      position_size_mode: "pct_available",
                      order_size_basis: "margin",
                      size_split_slots: false,
                      margin_mode: "isolated",
                    })
                  }
                >
                  OKX 방식 적용 (가용 % + 증거금 % + 격리)
                </button>
                <p className="order-size-preset-result">
                  가용 ${Math.round(portfolio.available).toLocaleString()} · {config.order_size_pct ?? 20}% →
                  증거금 ${Math.round(portfolio.available * ((config.order_size_pct ?? 20) / 100)).toLocaleString()}
                  {" · "}
                  명목 ${Math.round(
                    portfolio.available * ((config.order_size_pct ?? 20) / 100) * (config.leverage || 1),
                  ).toLocaleString()}{" "}
                  (레버 {config.leverage}x)
                </p>
              </div>
              <div className="order-size-preset-box">
                <strong>💡 총자산(Equity) 기준 {config.order_size_pct ?? 20}%로 1회 진입</strong>
                <ol>
                  <li>
                    주문 크기 방식 → <strong>총자산(Equity) %</strong>
                    {(config.position_size_mode || "fixed") !== "pct_equity" && (
                      <button
                        type="button"
                        className="preset-link"
                        onClick={() =>
                          patchConfig({ position_size_mode: "pct_equity" })
                        }
                      >
                        적용
                      </button>
                    )}
                  </li>
                  <li>
                    비율 기준 → <strong>증거금 %</strong> (잔고의 20%를 증거금으로) 또는{" "}
                    <strong>명목 %</strong> (잔고의 20%가 포지션 크기)
                  </li>
                  <li>
                    「잔고÷남은슬롯」 → <strong>체크 해제</strong>
                    {config.size_split_slots && (
                      <button
                        type="button"
                        className="preset-link"
                        onClick={() => patchConfig({ size_split_slots: false })}
                      >
                        끄기
                      </button>
                    )}
                  </li>
                  <li>비율 → <strong>{config.order_size_pct ?? 20}%</strong></li>
                </ol>
                <p className="order-size-preset-result">
                  현재 총자산 ${Math.round(portfolio.equity).toLocaleString()} 기준 예시 —{" "}
                  {balancePctGuide.title}
                  <br />
                  {balancePctGuide.lines.join(" · ")}
                </p>
              </div>
            </div>
            <div className="settings-row">
              <label>레버리지</label>
              <input type="number" value={config.leverage}
                onChange={(e) => patchConfig({ leverage: Number(e.target.value) })} />
            </div>
            {config.instrument_type !== "spot" && (
              <div className="settings-row">
                <label>마진 모드</label>
                <select
                  value={config.margin_mode || "isolated"}
                  onChange={(e) => patchConfig({ margin_mode: e.target.value })}
                >
                  <option value="isolated">격리 (Isolated) — 종목별 증거금 분리</option>
                  <option value="cross">교차 (Cross) — 계정 잔고 공유</option>
                </select>
              </div>
            )}
            <div className="settings-row">
              <label>손절 PnL% (SL)</label>
              <input type="number" step="0.1" value={config.stop_loss_pct}
                disabled={!!config.backtest_auto_sl_tp}
                title={config.backtest_auto_sl_tp ? "백테스트 SL/TP 자동이 켜져 있어 백테스트 결과로 갱신됩니다" : ""}
                onChange={(e) => patchConfig({ stop_loss_pct: Number(e.target.value) })} />
            </div>
            <div className="settings-row">
              <label>익절 PnL% (TP)</label>
              <input type="number" step="0.1" value={config.take_profit_pct}
                disabled={!!config.backtest_auto_sl_tp}
                title={config.backtest_auto_sl_tp ? "백테스트 SL/TP 자동이 켜져 있어 백테스트 결과로 갱신됩니다" : ""}
                onChange={(e) => patchConfig({ take_profit_pct: Number(e.target.value) })} />
            </div>
            <div className="settings-row settings-check-block">
              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={!!config.backtest_auto_sl_tp}
                  onChange={(e) =>
                    patchConfig({ backtest_auto_sl_tp: e.target.checked })
                  }
                />
                <span>
                  <strong>백테스트 SL/TP 자동 (승률 우선)</strong>
                  <br />
                  <span className="settings-check-desc">
                    체크 시: 종목별 백테스트 SL/TP 프로필을 자동매매 진입에 적용합니다.
                    (예: SHIB 1.5% 익절·승률 82% 구간) — ATR 대신 백테스트 최적값 사용.
                    프로필은 backend/data/symbol_sl_tp_profiles.json 에 누적됩니다.
                  </span>
                </span>
              </label>
            </div>
            <div className="settings-row settings-check-block">
              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={config.trend_scale_in !== false}
                  onChange={(e) => patchConfig({ trend_scale_in: e.target.checked })}
                />
                <span>
                  <strong>추세추종 추가진입</strong>
                  <br />
                  <span className="settings-check-desc">
                    수익권에서 체결량·EMA20/50·MACD·캔들이 같은 방향으로 강할 때만 기존 포지션에 추가진입합니다.
                  </span>
                </span>
              </label>
            </div>
            <div className="settings-row">
              <label>추가진입 최대 횟수</label>
              <input
                type="number"
                min={0}
                max={5}
                value={config.max_scale_ins ?? 2}
                disabled={config.trend_scale_in === false}
                onChange={(e) => patchConfig({ max_scale_ins: Number(e.target.value) })}
              />
            </div>
            <div className="settings-row">
              <label>추가진입 크기 (%)</label>
              <input
                type="number"
                min={5}
                max={100}
                step={5}
                value={config.scale_in_size_pct ?? 50}
                disabled={config.trend_scale_in === false}
                onChange={(e) => patchConfig({ scale_in_size_pct: Number(e.target.value) })}
              />
            </div>
            <div className="settings-row">
              <label>추가진입 최소 ROI%</label>
              <input
                type="number"
                min={0}
                step={0.5}
                value={config.scale_in_min_pnl_pct ?? 3}
                disabled={config.trend_scale_in === false}
                onChange={(e) => patchConfig({ scale_in_min_pnl_pct: Number(e.target.value) })}
              />
            </div>
            <div className="settings-row">
              <label>추세 이탈 확인 캔들</label>
              <input
                type="number"
                min={1}
                max={6}
                value={config.trend_exit_confirm_bars ?? 3}
                disabled={config.trend_scale_in === false}
                onChange={(e) => patchConfig({ trend_exit_confirm_bars: Number(e.target.value) })}
              />
            </div>
            <p style={{ fontSize: "0.75rem", color: "#8b949e", gridColumn: "1 / -1", marginTop: -6 }}>
              추세 이탈 청산 확인용입니다. 단타는 1캔들=5분, 장타는 1캔들=1시간입니다.
            </p>
            <p style={{ fontSize: "0.8rem", color: "#8b949e", gridColumn: "1 / -1" }}>
              단타 기본 SL {config.stop_loss_pct}% / TP {config.take_profit_pct}%
              {config.backtest_auto_sl_tp && " (자동 — 백테스트 완료 시 갱신)"}
              {config.strategy_mode === "swing" && " (장타: 차트 ATR·고저 — 넓은 구간 자동)"}
              {config.strategy_mode === "both" &&
                " (단타·장타 동시, SL/TP는 종목별 차트 변동성·구조로 자동)"}
              {config.strategy_mode === "scalp" && " (단타: 차트 ATR·저점/고점 기준 자동 SL/TP)"}
            </p>
            <div className="settings-row">
              <label>최대 포지션</label>
              <input type="number" value={config.max_positions}
                onChange={(e) => patchConfig({ max_positions: Number(e.target.value) })} />
            </div>
            <div className="settings-row">
              <label>진입 방향</label>
              <select
                value={config.position_side || "auto"}
                onChange={(e) => patchConfig({ position_side: e.target.value })}
              >
                <option value="auto">AI 자동</option>
                <option value="long">롱만</option>
                <option value="short">숏만</option>
              </select>
            </div>
            <div className="settings-row settings-check-block">
              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={!!config.backtest_auto_settings}
                  onChange={(e) =>
                    patchConfig({ backtest_auto_settings: e.target.checked })
                  }
                />
                <span>
                  <strong>백테스트 유동 설정 (자동)</strong>
                  <br />
                  <span className="settings-check-desc">
                    체크 시: 백테스트가 끝날 때마다 추천 min_score만 자동 반영됩니다.
                    주문 크기(총자산 %·비율 등)는 위 설정을 그대로 사용합니다.
                  </span>
                </span>
              </label>
            </div>
            <div className="settings-row">
              <label>최소 점수 {config.backtest_auto_settings ? "(자동)" : "(수동 고정)"}</label>
              <input
                type="number"
                value={config.min_score}
                disabled={!!config.backtest_auto_settings}
                title={
                  config.backtest_auto_settings
                    ? "백테스트 자동 설정이 켜져 있어 백테스트 결과로 갱신됩니다"
                    : ""
                }
                onChange={(e) => patchConfig({ min_score: Number(e.target.value) })}
              />
            </div>
            <div className="settings-row">
              <label>데모 모드</label>
              <select value={config.okx_flag}
            onChange={(e) => patchConfig({ okx_flag: e.target.value })}>
                <option value="1">데모 API</option>
                <option value="0">실거래 API</option>
              </select>
            </div>
          </div>
          {config.api_keys_configured && (
            <p style={{ color: "#3fb950", fontSize: "0.875rem", margin: "12px 0 8px" }}>
              API 키 저장됨 — 변경 시에만 다시 입력
            </p>
          )}
          <div className="settings-grid">
            <div className="settings-row">
              <label>API Key</label>
              <input type="password" placeholder={config.api_keys_configured ? "저장됨" : "API Key"}
                value={apiDraft.key} onChange={(e) => { lockConfigEdits(); setApiDraft((d) => ({ ...d, key: e.target.value })); }} />
            </div>
            <div className="settings-row">
              <label>API Secret</label>
              <input type="password" placeholder={config.api_keys_configured ? "저장됨" : "Secret"}
                value={apiDraft.secret} onChange={(e) => { lockConfigEdits(); setApiDraft((d) => ({ ...d, secret: e.target.value })); }} />
            </div>
            <div className="settings-row">
              <label>Passphrase</label>
              <input type="password" placeholder={config.api_keys_configured ? "저장됨" : "Passphrase"}
                value={apiDraft.pass} onChange={(e) => { lockConfigEdits(); setApiDraft((d) => ({ ...d, pass: e.target.value })); }} />
            </div>
          </div>
          <div className="settings-save-row">
            <button
              className="primary"
              onClick={handleSaveConfig}
              disabled={configSaveStatus === "saving"}
            >
              {configSaveStatus === "saving" ? "저장 중…" : "설정 저장"}
            </button>
            {configSaveStatus === "saved" && (
              <span className="save-status saved">✓ 설정 저장됨</span>
            )}
            {configSaveStatus === "error" && (
              <span className="save-status error">저장 실패 — 다시 시도</span>
            )}
          </div>
        </div>
      )}

      {mainTab === "backtest" ? (
        <BacktestPanel
          config={config}
          bundle={data.backtest ?? null}
          onRefresh={refresh}
          onConfigApplied={(minScore) => patchConfig({ min_score: minScore })}
          onPatchConfig={patchConfig}
        />
      ) : mainTab === "exits" ? (
        <ExitHistoryPanel
          trades={data.trades ?? []}
          filter={exitFilter}
          onFilter={setExitFilter}
        />
      ) : (
        <>
      {config.trade_mode === "live" && data.portfolio_sync_message && (
        <p className="live-sync-banner">
          {data.portfolio_source === "okx" ? "🔗 " : ""}
          {data.portfolio_sync_message}
        </p>
      )}

      <div className="grid">
        <div className="card">
          <h3>자산 (Equity · {moneyTag}){config.trade_mode === "live" ? " · OKX" : ""}</h3>
          <div className="value">{fmtUsd(portfolio.equity, 2)}</div>
        </div>
        <div className="card">
          <h3>가용 잔고 ({moneyTag}){config.trade_mode === "live" ? " · OKX" : ""}</h3>
          <div className="value">{fmtUsd(portfolio.available, 2)}</div>
        </div>
        <div className="card">
          <h3>1회 주문 규모 (USD)</h3>
          <div className="value" style={{ fontSize: "1.1rem" }}>
            {fmtUsd(nextOrderUsdt, 0)}
          </div>
          <div style={{ fontSize: "0.75rem", color: "#8b949e", marginTop: 4 }}>
            {positionSizeModeLabel(config.position_size_mode)}
            {config.position_size_mode !== "fixed" && ` ${config.order_size_pct ?? 2}%`}
          </div>
        </div>
        <div className="card">
          <h3>미실현 PnL</h3>
          <div className={`value ${portfolio.unrealized_pnl >= 0 ? "positive" : "negative"}`}>
            {portfolio.unrealized_pnl >= 0 ? "+" : ""}${fmtPnlUsdt(portfolio.unrealized_pnl)}
          </div>
        </div>
        <div className="card">
          <h3>실현 PnL / 승률</h3>
          <div className={`value ${portfolio.realized_pnl >= 0 ? "positive" : "negative"}`}>
            {portfolio.realized_pnl >= 0 ? "+" : ""}{fmtUsd(portfolio.realized_pnl, 2)}
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
          {data.link_message && data.link_message.includes("환경") && (
            <p style={{ fontSize: "0.75rem", color: "#f85149", marginTop: 6 }}>
              데모 API 키 → 설정에서 「데모」 / 실거래 키 → 「실거래」 선택 후 다시 테스트
            </p>
          )}
        </div>
      </div>

      <AssetAllocationPanel
        portfolio={portfolio}
        defaultLeverage={config.leverage}
        tradeMode={config.trade_mode}
        moneyTag={moneyTag}
      />

      <div className="section">
        <h2>보유 포지션 ({portfolio.positions.length}) — 행 클릭 또는 「차트」</h2>
        {portfolio.positions.length === 0 ? (
          <p style={{ color: "#8b949e" }}>포지션 없음</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>종목</th>
                <th>방향</th>
                <th>레버</th>
                <th>수량</th>
                <th>진입가</th>
                <th>현재가</th>
                <th>명목</th>
                <th>PnL(USDT)</th>
                <th>SL / TP</th>
                <th>전략</th>
                <th>차트</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr
                  key={p.id}
                  className="clickable-row"
                  onClick={() => openPositionChart(p)}
                  title="클릭하여 차트 보기"
                >
                  <td>{p.inst_id}</td>
                  <td><span className={`badge ${p.side}`}>{p.side.toUpperCase()}</span></td>
                  <td>
                    {p.instrument_type === "spot"
                      ? "—"
                      : `${(p.leverage && p.leverage > 0 ? p.leverage : config.leverage)}x`}
                  </td>
                  <td>{fmtNum(p.quantity, 4)}</td>
                  <td>${fmtPrice(p.entry_price)}</td>
                  <td>
                    ${fmtPrice(p.current_price)}
                    {p.liquidation_price && p.liquidation_price > 0 && (
                      <div className={liqRisk(p) ? "liq-risk warn" : "liq-risk"}>
                        청산 ${fmtPrice(p.liquidation_price)}
                        {liqRisk(p) && ` · ${liqRisk(p)}`}
                      </div>
                    )}
                  </td>
                  <td className="muted" title="포지션 명목 가치">
                    ${fmtNum(
                      p.notional_usdt && p.notional_usdt > 0
                        ? p.notional_usdt
                        : p.quantity * (p.current_price || p.entry_price),
                      0,
                    )}
                  </td>
                  <td className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>
                    {p.unrealized_pnl >= 0 ? "+" : ""}{fmtPnlUsdt(p.unrealized_pnl)} USDT (ROI {fmtNum(p.unrealized_pnl_pct, 1)}%)
                  </td>
                  <td className="sl-tp-col">
                    <PositionSlTpEditor position={p} onSaved={refresh} />
                  </td>
                  <td>
                    <span className={`badge ${p.strategy_mode === "swing" ? "swing" : "long"}`}>
                      {p.strategy_mode === "swing" ? "장타" : "단타"}
                    </span>
                    {(p.scale_in_count ?? 0) > 0 && (
                      <div className="muted" style={{ marginTop: 4, fontSize: "0.7rem" }}>
                        추가진입 {p.scale_in_count}회
                      </div>
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button type="button" onClick={() => openPositionChart(p)}>차트</button>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button type="button" onClick={() => closePosition(p.inst_id).then(refresh)}>청산</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {(data.pending_orders?.length ?? 0) > 0 && (
        <div className="section pending-orders">
          <h2>미체결 주문 ({data.pending_orders?.length ?? 0})</h2>
          <table>
            <thead>
              <tr>
                <th>종목</th>
                <th>방향</th>
                <th>종류</th>
                <th>가격</th>
                <th>수량</th>
                <th>체결</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {data.pending_orders?.map((o) => (
                <tr key={o.ord_id || `${o.inst_id}-${o.ts}`}>
                  <td>{o.inst_id}</td>
                  <td>{o.side.toUpperCase()} {o.pos_side && `(${o.pos_side})`}</td>
                  <td>{o.order_type}</td>
                  <td>${fmtPrice(o.price)}</td>
                  <td>{fmtNum(o.size, 4)}</td>
                  <td>{fmtNum(o.filled_size, 4)}</td>
                  <td>{o.state || "live"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="section decision-log-section">
        <h2>AI 판단 로그 ({decisionLogs.length})</h2>
        <div className="log-scroll decision-log-scroll">
          {decisionLogs.length === 0 ? (
            <p className="empty-log">아직 판단 로그가 없습니다. 자동매매 스캔이 돌면 후보 평가·진입 통과·거절 사유가 여기에 표시됩니다.</p>
          ) : (
            decisionLogs.slice(0, 80).map((log, i) => (
              <div key={i} className={`log-entry ${log.level}`}>
                <span className="ts">{log.ts?.slice(11, 19)}</span>
                {log.message}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="section">
        <h2>매매 후보 (AI 분석) — 행 클릭·차트 버튼</h2>
        {candidates.length === 0 ? (
          <p style={{ color: "#8b949e" }}>스캔 버튼을 눌러 분석하세요</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>종목</th>
                <th>가격</th>
                <th className="chart-col">차트</th>
                <th>24h</th>
                <th>거래량</th>
                <th>RSI</th>
                <th>추세</th>
                <th>점수</th>
                <th>판단</th>
                <th>근거</th>
                <th>수동</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <CandidateRows
                  key={c.inst_id}
                  c={c}
                  config={config}
                  orderSizeUsdt={nextOrderUsdt}
                  expanded={expandedCandidateId === c.inst_id}
                  onToggle={() =>
                    setExpandedCandidateId(
                      expandedCandidateId === c.inst_id ? null : c.inst_id,
                    )
                  }
                  onOpenChart={() => openCandidateChart(c)}
                  onRefresh={refresh}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="section">
        <h2>활동 로그</h2>
        <div className="log-scroll">
          {bot.activity_log.slice(0, 120).map((log, i) => (
            <div
              key={i}
              className={`log-entry ${log.level}${log.phase === "config" ? " config" : ""}`}
            >
              <span className="ts">{log.ts?.slice(11, 19)}</span>
              <span className="phase">[{log.phase}]</span> {log.message}
            </div>
          ))}
        </div>
      </div>
        </>
      )}
    </div>
  );
}

const CLOSE_TYPE_LABEL: Record<string, string> = {
  sl: "손절",
  tp: "익절",
  trail: "트레일링",
  emergency: "긴급",
  manual: "수동",
  other: "기타",
};

function exitPriceDelta(t: TradeRecord): React.ReactNode {
  const entry = t.entry_price ?? 0;
  const exit = t.exit_price ?? t.price ?? 0;
  if (entry <= 0 || exit <= 0) return "—";
  const pct = ((exit - entry) / entry) * 100;
  const cls = pct >= 0 ? "positive" : "negative";
  const sign = pct >= 0 ? "+" : "";
  return (
    <span className={cls} title="진입가 대비 청산가 변동률">
      {sign}
      {fmtNum(pct, 2)}%
    </span>
  );
}

function ExitHistoryPanel({
  trades,
  filter,
  onFilter,
}: {
  trades: TradeRecord[];
  filter: "all" | "sl" | "tp" | "other";
  onFilter: (f: "all" | "sl" | "tp" | "other") => void;
}) {
  const sorted = [...trades].reverse();
  const filtered = sorted.filter((t) => {
    const ct = t.close_type || "";
    if (filter === "all") return true;
    if (filter === "sl") return ct === "sl";
    if (filter === "tp") return ct === "tp";
    return ct !== "sl" && ct !== "tp";
  });

  const slTrades = trades.filter((t) => t.close_type === "sl");
  const tpTrades = trades.filter((t) => t.close_type === "tp");
  const slPnl = slTrades.reduce((s, t) => s + t.pnl, 0);
  const tpPnl = tpTrades.reduce((s, t) => s + t.pnl, 0);

  return (
    <div className="exit-history">
      <div className="exit-summary grid">
        <div className="card">
          <h3>손절</h3>
          <div className="value negative">{slTrades.length}건</div>
          <div className={`sub ${slPnl >= 0 ? "positive" : "negative"}`}>
            합계 {slPnl >= 0 ? "+" : ""}{fmtNum(slPnl)}
          </div>
        </div>
        <div className="card">
          <h3>익절</h3>
          <div className="value positive">{tpTrades.length}건</div>
          <div className={`sub ${tpPnl >= 0 ? "positive" : "negative"}`}>
            합계 {tpPnl >= 0 ? "+" : ""}{fmtNum(tpPnl)}
          </div>
        </div>
        <div className="card">
          <h3>전체 청산</h3>
          <div className="value">{trades.length}건</div>
          <div className="sub" style={{ color: "#8b949e" }}>
            모의·실거래 청산 시 자동 기록
          </div>
        </div>
      </div>

      <div className="exit-filters">
        {(["all", "sl", "tp", "other"] as const).map((f) => (
          <button
            key={f}
            type="button"
            className={filter === f ? "active" : ""}
            onClick={() => onFilter(f)}
          >
            {f === "all" ? "전체" : f === "sl" ? "손절만" : f === "tp" ? "익절만" : "기타"}
          </button>
        ))}
      </div>

      <div className="section">
        <h2>청산 내역 ({filtered.length})</h2>
        {filtered.length === 0 ? (
          <p style={{ color: "#8b949e" }}>
            아직 기록이 없습니다. 포지션이 손절·익절·수동 청산되면 여기에 쌓입니다.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>시각</th>
                <th>종목</th>
                <th>방향</th>
                <th>구분</th>
                <th>전략</th>
                <th>진입 시세</th>
                <th>청산 시세</th>
                <th>가격 변동</th>
                <th>명목</th>
                <th>PnL(USDT)</th>
                <th>사유</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={`${t.id}-${t.ts}`}>
                  <td className="ts-cell">{t.ts?.slice(0, 19).replace("T", " ")}</td>
                  <td>{t.inst_id}</td>
                  <td>
                    <span className={`badge ${t.position_side || ""}`}>
                      {(t.position_side || "").toUpperCase() || "—"}
                    </span>
                  </td>
                  <td>
                    <span className={`badge close-${t.close_type || "other"}`}>
                      {CLOSE_TYPE_LABEL[t.close_type || "other"] ?? t.close_type}
                    </span>
                  </td>
                  <td>{t.strategy_mode === "swing" ? "장타" : t.strategy_mode ? "단타" : "—"}</td>
                  <td className="price-cell" title="진입 체결 시점 코인 USDT 가격">
                    ${fmtPrice(t.entry_price ?? 0)}
                  </td>
                  <td className="price-cell" title="청산(손절·익절) 시점 코인 USDT 가격">
                    ${fmtPrice(t.exit_price ?? t.price)}
                  </td>
                  <td className="price-delta-cell">
                    {exitPriceDelta(t)}
                  </td>
                  <td>${fmtNum(t.notional_usdt ?? 0, 0)}</td>
                  <td className={t.pnl >= 0 ? "positive" : "negative"}>
                    {t.pnl >= 0 ? "+" : ""}{fmtNum(t.pnl)} USDT (ROI {fmtNum(t.pnl_pct, 1)}%)
                  </td>
                  <td style={{ fontSize: "0.8rem", color: "#8b949e", maxWidth: 220 }}>
                    {t.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function CandidateRows({
  c,
  config,
  orderSizeUsdt,
  expanded,
  onToggle,
  onOpenChart,
  onRefresh,
}: {
  c: CoinCandidate;
  config: AppConfig;
  orderSizeUsdt: number;
  expanded: boolean;
  onToggle: () => void;
  onOpenChart: () => void;
  onRefresh: () => void;
}) {
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [limitPrice, setLimitPrice] = useState(fmtPrice(c.last_price));
  const [manualMsg, setManualMsg] = useState("");
  const [manualBusy, setManualBusy] = useState(false);

  const submitManual = async (side: "long" | "short") => {
    const px = Number(limitPrice);
    if (orderType === "limit" && (!Number.isFinite(px) || px <= 0)) {
      setManualMsg("지정가를 입력하세요");
      return;
    }
    setManualBusy(true);
    setManualMsg("");
    try {
      const res = await manualOrder(
        c.inst_id,
        side,
        orderSizeUsdt,
        config.leverage,
        orderType,
        orderType === "limit" ? px : 0,
      );
      setManualMsg(res.ok ? (res.message || "주문 완료") : (res.message || "주문 실패"));
      onRefresh();
    } catch {
      setManualMsg("주문 요청 실패");
    } finally {
      setManualBusy(false);
    }
  };

  return (
    <>
      <tr
        className={expanded ? "row-expanded" : ""}
        onClick={onToggle}
        style={{ cursor: "pointer" }}
      >
        <td>{c.inst_id}</td>
        <td>${fmtPrice(c.last_price)}</td>
        <td className="chart-col" onClick={(e) => e.stopPropagation()}>
          {c.ohlc_bars?.length ? <MiniCandles bars={c.ohlc_bars} /> : <MiniCandles bars={[]} />}
        </td>
        <td className={c.change_24h_pct >= 0 ? "positive" : "negative"}>
          {c.change_24h_pct >= 0 ? "+" : ""}{fmtNum(c.change_24h_pct, 1)}%
        </td>
        <td>${fmtVolumeUsdt(c.volume_24h_usdt)}</td>
        <td onClick={(e) => e.stopPropagation()}><RsiGauge rsi={c.rsi} /></td>
        <td>{c.trend}</td>
        <td>
          <strong>{fmtNum(c.score, 0)}</strong>
          <div className="score-bar">
            <div className="fill" style={{ width: `${Math.min(Math.max(c.score, 0), 100)}%` }} />
          </div>
        </td>
        <td>
          <span
            className={`badge ${c.outlook === "short" ? "short" : c.outlook === "long" ? "long" : ""}`}
            title={
              c.outlook === "long"
                ? "상승 예상 → 롱"
                : c.outlook === "short"
                  ? "하락·고점 예상 → 숏"
                  : "관망"
            }
          >
            {c.outlook === "long" ? "롱" : c.outlook === "short" ? "숏" : c.outlook}
          </span>
          {c.scalp_ok ? " ✓단타" : ""}
          {c.swing_ok ? " ✓장타" : ""}
          {c.short_scalp_ok ? " ✓숏단" : ""}
          {c.short_swing_ok ? " ✓숏장" : ""}
        </td>
        <td style={{ fontSize: "0.75rem", color: "#8b949e" }}>{c.reasons.slice(0, 3).join(", ")}</td>
        <td className="manual-cell" onClick={(e) => e.stopPropagation()}>
          <div className="manual-btns">
            <button type="button" onClick={onOpenChart}>차트</button>
            <button
              className="long"
              disabled={manualBusy}
              onClick={() => submitManual("long")}
            >
              롱
            </button>
            {config.instrument_type !== "spot" && (
              <button
                className="short"
                disabled={manualBusy}
                onClick={() => submitManual("short")}
              >
                숏
              </button>
            )}
          </div>
          <div className="manual-order-controls">
            <select value={orderType} onChange={(e) => setOrderType(e.target.value as "market" | "limit")}>
              <option value="market">시장가</option>
              <option value="limit">지정가</option>
            </select>
            <input
              type="number"
              min={0}
              step="any"
              value={limitPrice}
              disabled={orderType === "market"}
              onChange={(e) => setLimitPrice(e.target.value)}
              aria-label={`${c.inst_id} 지정가`}
            />
            <button
              type="button"
              disabled={manualBusy}
              onClick={() => setLimitPrice(fmtPrice(c.last_price))}
            >
              현재가
            </button>
          </div>
          {manualMsg && (
            <div className={manualMsg.includes("실패") || manualMsg.includes("오류") ? "manual-msg error" : "manual-msg"}>
              {manualMsg}
            </div>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="row-expanded">
          <td colSpan={11}>
            <div className="candidate-detail">
              <div className="candidate-detail-head">
                <strong>{c.inst_id}</strong>
                <span>가격 ${fmtPrice(c.last_price)}</span>
                <span>점수 {fmtNum(c.score, 0)}</span>
                <span>추세 {c.trend}</span>
              </div>
              <button type="button" className="primary" style={{ marginBottom: 8 }} onClick={onOpenChart}>
                전체 차트 열기 (2종)
              </button>
              <CandleChart
                instId={c.inst_id}
                strategy={
                  config.strategy_mode === "both"
                    ? (c.swing_ok && !c.scalp_ok ? "swing" : "scalp")
                    : chartStrategyKey(config.strategy_mode)
                }
                height={280}
                pro
                levels={(() => {
                  const cs =
                    config.strategy_mode === "both"
                      ? (c.swing_ok && !c.scalp_ok ? "swing" : "scalp")
                      : chartStrategyKey(config.strategy_mode);
                  const pct = slTpPctForStrategy(cs);
                  return {
                    slPct: pct.sl,
                    tpPct: pct.tp,
                    side: c.outlook === "short" ? "short" : "long",
                  };
                })()}
              />
              <p style={{ fontSize: "0.8125rem", color: "#8b949e", marginTop: 8 }}>
                {c.reasons.join(" · ")}
              </p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>
);
