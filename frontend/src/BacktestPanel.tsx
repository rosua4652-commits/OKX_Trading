import { useCallback, useEffect, useRef, useState } from "react";
import { applyBacktest, cancelBacktest, fetchBacktestStatus, runBacktest, updateConfig } from "./api";
import { BacktestCandlesGrid, TradeMiniCandle } from "./BacktestCandles";
import { fmtNum, fmtPrice, fmtUsd } from "./format";
import type {
  AppConfig,
  BacktestBundle,
  BacktestHistoryEntry,
  BacktestResult,
  SymbolSlTpProfile,
} from "./types";

type NumberInput = number | "";

function calcCandleLimit(months: number, strategyMode: string): number {
  const days = months * 30;
  return strategyMode === "swing" ? days * 24 : days * 288;
}

function candleDesc(limit: number, strategyMode: string): string {
  if (!limit) return "";
  const minutesPerCandle = strategyMode === "swing" ? 60 : 5;
  const totalHours = (limit * minutesPerCandle) / 60;
  if (totalHours < 48) return `≈ ${Math.round(totalHours)}시간`;
  const days = Math.round(totalHours / 24);
  if (days < 30) return `≈ ${days}일`;
  return `≈ ${(days / 30).toFixed(1)}개월`;
}

type Props = {
  config: AppConfig;
  bundle?: BacktestBundle;
  onRefresh: () => Promise<void> | void;
  onConfigApplied?: (config: AppConfig) => void;
  onPatchConfig?: (patch: Partial<AppConfig>) => void;
};

const toNumberInput = (value: unknown, fallback: number): NumberInput => {
  if (value === "") return "";
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const fmtPct = (value?: number) =>
  typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "-";

const fmtSide = (side?: string) => {
  const s = String(side ?? "").toLowerCase();
  if (s.includes("short")) return "SHORT";
  if (s.includes("long")) return "LONG";
  return side || "-";
};

const KST_TZ = "Asia/Seoul";

function toDateObj(ts?: string): Date | null {
  if (!ts) return null;
  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatKstTime(ts?: string, withDate = false): string {
  const d = toDateObj(ts);
  if (!d) return ts || "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TZ,
    month: withDate ? "2-digit" : undefined,
    day: withDate ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
}

function phaseLabel(phase?: string): string {
  switch (phase) {
    case "start":
      return "시작";
    case "fetch":
      return "캔들 수집";
    case "simulate":
      return "시뮬레이션";
    case "feedback":
      return "피드백 분석";
    case "scheduled":
      return "예약 실행";
    case "done":
      return "완료";
    case "cancelled":
      return "취소됨";
    case "error":
      return "오류";
    case "idle":
    case undefined:
    case "":
      return "대기";
    default:
      return phase;
  }
}

function MetricsCards({ result }: { result: BacktestResult | null }) {
  const m = result?.metrics;
  const z = result?.zone_walkforward;
  return (
    <div className="grid backtest-summary">
      <div className="card">
        <h3>순손익</h3>
        <p className={(m?.total_pnl ?? 0) >= 0 ? "green" : "red"}>{fmtUsd(m?.total_pnl ?? 0)}</p>
        <div className="sub">ROI {fmtPct(m?.total_pnl_pct)} · 수수료 {fmtUsd(m?.total_fees_usdt ?? 0)}</div>
      </div>
      <div className="card">
        <h3>승률 / 거래</h3>
        <p>{fmtPct(m?.win_rate)}</p>
        <div className="sub">{m?.trade_count ?? 0}건 · 롱 {m?.long_trades ?? 0} / 숏 {m?.short_trades ?? 0}</div>
      </div>
      <div className="card">
        <h3>MDD</h3>
        <p className="red">{fmtPct(m?.max_drawdown_pct)}</p>
        <div className="sub">평균 진입 점수 {fmtNum(m?.avg_score_entries ?? 0, 1)}</div>
      </div>
      <div className="card">
        <h3>ATR 검증</h3>
        <p>{fmtPct(z?.accuracy_pct)}</p>
        <div className="sub">Forward {fmtNum(z?.avg_forward_r ?? 0, 2)}R · 샘플 {z?.samples ?? 0}</div>
      </div>
    </div>
  );
}

function Recommendation({ result, config }: { result: BacktestResult | null; config: AppConfig }) {
  const rec = result?.recommendation;
  if (!rec) return null;
  const protectTrigger = rec.profit_protect_trigger_pct && rec.profit_protect_trigger_pct > 0
    ? rec.profit_protect_trigger_pct
    : (config.profit_protect_trigger_pct ?? 3);
  const protectConfirm = rec.profit_protect_confirm_sec && rec.profit_protect_confirm_sec > 0
    ? rec.profit_protect_confirm_sec
    : (config.profit_protect_confirm_sec ?? 10);
  return (
    <div className="section">
      <h2>추천 설정</h2>
      <div className="bt-auto-hint">
        min_score {rec.min_score} · 방향 {rec.direction ?? "auto"} · SL {fmtPct(rec.stop_loss_pct)} / TP{" "}
        {fmtPct(rec.take_profit_pct)} · 보호 {fmtPct(protectTrigger)} of TP / {protectConfirm}초
      </div>
      <p className="bt-note">{rec.reason}</p>
      {rec.sl_tp_reason && <p className="bt-note">{rec.sl_tp_reason}</p>}
      {rec.profit_protect_reason && <p className="bt-note">{rec.profit_protect_reason}</p>}
      {!!rec.trials?.length && (
        <div className="bt-scroll">
          <table>
            <thead>
              <tr><th>min_score</th><th>순손익</th><th>승률</th><th>거래</th><th>롱/숏</th></tr>
            </thead>
            <tbody>
              {rec.trials.slice(0, 8).map((t) => (
                <tr key={`${t.min_score}-${t.total_pnl}-${t.trades}`}>
                  <td>{t.min_score}</td>
                  <td className={t.total_pnl >= 0 ? "green" : "red"}>{fmtUsd(t.total_pnl)}</td>
                  <td>{fmtPct(t.win_rate)}</td>
                  <td>{t.trades}</td>
                  <td>{t.long_entries}/{t.short_entries}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!!rec.profit_protect_trials?.length && (
        <div className="bt-scroll" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr><th>보호 시작</th><th>유지</th><th>순손익</th><th>승률</th><th>거래</th><th>보호청산</th></tr>
            </thead>
            <tbody>
              {rec.profit_protect_trials.slice(0, 8).map((t) => (
                <tr key={`${t.trigger_pct_of_tp}-${t.confirm_sec}-${t.total_pnl}-${t.trades}`}>
                  <td>{fmtPct(t.trigger_pct_of_tp)} of TP</td>
                  <td>{t.confirm_sec}초</td>
                  <td className={t.total_pnl >= 0 ? "green" : "red"}>{fmtUsd(t.total_pnl)}</td>
                  <td>{fmtPct(t.win_rate)}</td>
                  <td>{t.trades}</td>
                  <td>{t.protect_hits ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SymbolProfiles({ profiles }: { profiles?: SymbolSlTpProfile[] }) {
  if (!profiles?.length) return null;
  return (
    <div className="section">
      <h2>종목별 SL/TP 프로필</h2>
      <div className="bt-scroll">
        <table>
          <thead><tr><th>종목</th><th>SL</th><th>TP</th><th>승률</th><th>거래</th><th>TP/SL</th></tr></thead>
          <tbody>
            {profiles.slice(0, 20).map((p) => (
              <tr key={p.inst_id}>
                <td>{p.inst_id}</td><td>{fmtPct(p.stop_loss_pct)}</td><td>{fmtPct(p.take_profit_pct)}</td>
                <td>{fmtPct(p.win_rate)}</td><td>{p.trades}</td><td>{p.tp_hits ?? 0}/{p.sl_hits ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradesTable({ result }: { result: BacktestResult | null }) {
  const trades = result?.trades ?? [];
  if (!trades.length) return null;
  return (
    <div className="section">
      <h2>최근 백테스트 거래</h2>
      <div className="bt-scroll">
        <table>
          <thead><tr><th>종목</th><th>방향</th><th>전략</th><th>진입</th><th>청산</th><th>PnL</th><th>사유</th><th>캔들</th></tr></thead>
          <tbody>
            {trades.slice(-30).reverse().map((t, idx) => (
              <tr key={`${t.inst_id}-${t.entry_bar}-${t.exit_bar}-${idx}`}>
                <td>{t.inst_id}</td>
                <td><span className={`badge ${fmtSide(t.side).toLowerCase()}`}>{fmtSide(t.side)}</span></td>
                <td>{t.strategy}</td><td>{fmtPrice(t.entry_price)}</td><td>{fmtPrice(t.exit_price)}</td>
                <td className={t.pnl_usdt >= 0 ? "green" : "red"}>{fmtUsd(t.pnl_usdt)} ({fmtPct(t.pnl_pct)})</td>
                <td>{t.exit_reason}</td>
                <td><TradeMiniCandle instId={t.inst_id} entryBar={t.entry_bar} exitBar={t.exit_bar} charts={result?.symbol_charts} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ZoneWalkForward({ result }: { result: BacktestResult | null }) {
  const z = result?.zone_walkforward;
  if (!z?.details?.length) return null;
  return (
    <div className="section">
      <h2>ATR 구조 구간 예측 검증</h2>
      <div className="grid">
        <div className="card"><h3>구간 정확도</h3><p>{fmtPct(z.accuracy_pct)}</p><div className="sub">롱 {fmtPct(z.long_accuracy_pct)} / 숏 {fmtPct(z.short_accuracy_pct)}</div></div>
        <div className="card"><h3>평균 Forward R</h3><p className={z.avg_forward_r >= 0 ? "green" : "red"}>{fmtNum(z.avg_forward_r, 2)}R</p><div className="sub">실패 돌파 {fmtPct(z.false_break_pct)}</div></div>
      </div>
      <div className="bt-scroll">
        <table>
          <thead>
            <tr>
              <th>종목</th>
              <th>방향</th>
              <th>근거</th>
              <th>ATR%</th>
              <th>박스폭</th>
              <th>결과</th>
              <th>Forward R</th>
            </tr>
          </thead>
          <tbody>
            {z.details.slice(0, 20).map((d, idx) => (
              <tr key={`${d.inst_id}-${d.bar}-${idx}`}>
                <td>{d.inst_id}</td>
                <td>{fmtSide(d.direction)}</td>
                <td>{d.reason}</td>
                <td>{fmtPct(d.atr_pct)}</td>
                <td>{fmtNum(d.width_atr, 2)} ATR</td>
                <td>{d.hit ? "적중" : d.false_break ? "실패돌파" : "미확정"}</td>
                <td>{fmtNum(d.forward_r, 2)}R</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HistoryTable({ history }: { history?: BacktestHistoryEntry[] }) {
  if (!history?.length) return null;
  return (
    <div className="section">
      <h2>누적 백테스트 기록</h2>
      <div className="bt-scroll">
        <table>
          <thead><tr><th>시각</th><th>상태</th><th>종목</th><th>순손익</th><th>승률</th><th>거래</th><th>추천</th></tr></thead>
          <tbody>
            {history.slice(0, 30).map((h) => (
              <tr key={h.id}>
                <td>{formatKstTime(h.finished_at, true)}</td><td>{h.status}</td><td>{h.symbols?.slice(0, 4).join(", ")}</td>
                <td className={(h.metrics?.total_pnl ?? 0) >= 0 ? "green" : "red"}>{fmtUsd(h.metrics?.total_pnl ?? 0)}</td>
                <td>{fmtPct(h.metrics?.win_rate)}</td><td>{h.trade_count}</td>
                <td>{h.recommendation ? `${h.recommendation.min_score} · SL ${fmtPct(h.recommendation.stop_loss_pct)} / TP ${fmtPct(h.recommendation.take_profit_pct)}` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function BacktestPanel({ config, bundle, onRefresh, onConfigApplied, onPatchConfig }: Props) {
  const [running, setRunning] = useState(Boolean(bundle?.status?.running));
  const [msg, setMsg] = useState(bundle?.status?.message ?? "");
  const [candleLimit, setCandleLimit] = useState<NumberInput>(toNumberInput(config.backtest_candle_limit, 500));
  const [periodMonths, setPeriodMonths] = useState<3 | 6>(config.backtest_period_months === 6 ? 6 : 3);
  const [intervalInput, setIntervalInput] = useState<NumberInput>(toNumberInput(config.backtest_interval_minutes, 60));
  const [optimize, setOptimize] = useState(true);
  const saveTimer = useRef<number | null>(null);

  useEffect(() => { setRunning(Boolean(bundle?.status?.running)); setMsg(bundle?.status?.message ?? ""); }, [bundle?.status?.message, bundle?.status?.running]);
  useEffect(() => { setCandleLimit(toNumberInput(config.backtest_candle_limit, 500)); }, [config.backtest_candle_limit]);
  useEffect(() => { setPeriodMonths(config.backtest_period_months === 6 ? 6 : 3); }, [config.backtest_period_months]);
  useEffect(() => { setIntervalInput(toNumberInput(config.backtest_interval_minutes, 60)); }, [config.backtest_interval_minutes]);

  const saveBacktestConfig = useCallback((patch: Partial<AppConfig>) => {
    onPatchConfig?.(patch);
    const next = { ...config, ...patch };
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      const res = await updateConfig(next);
      if (res.config) onConfigApplied?.(res.config);
      await onRefresh();
    }, 350);
  }, [config, onConfigApplied, onPatchConfig, onRefresh]);

  useEffect(() => () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); }, []);

  const result = bundle?.result ?? null;
  const status = bundle?.status;
  const profiles = bundle?.symbol_profiles ?? Object.values(result?.symbol_profiles ?? {});
  const displayMessage = status?.running ? (status.message || msg) : (msg || status?.message);

  async function handleRun() {
    const limit = Math.max(80, Math.min(60000, Number(candleLimit) || 500));
    setRunning(true);
    const res = await runBacktest({ symbols: config.scan_symbols?.slice(0, 8) ?? [], candle_limit: limit, months: periodMonths, optimize });
    setMsg(res.message ?? "");
    if (!res.ok) setRunning(false);
    await onRefresh();
  }

  async function handleCancel() {
    const res = await cancelBacktest();
    setMsg(res.message ?? "");
    setRunning(false);
    await onRefresh();
  }

  async function handleApply() {
    const res = await applyBacktest();
    setMsg(res.message ?? "");
    if (res.config) onConfigApplied?.(res.config);
    await onRefresh();
  }

  async function refreshBacktest() {
    const res = await fetchBacktestStatus();
    setRunning(res.status.running);
    setMsg(res.status.message ?? "");
    await onRefresh();
  }

  return (
    <div className="backtest-panel">
      <div className="backtest-toolbar">
        <button className="primary" onClick={handleRun} disabled={running}>{running ? "백테스트 실행 중..." : "백테스트 실행"}</button>
        {running && <button className="danger" onClick={handleCancel}>취소</button>}
        <button onClick={handleApply}>추천 설정 적용</button>
        <button onClick={refreshBacktest}>상태 새로고침</button>
        <label>기간
          <select value={periodMonths} onChange={(e) => {
            const months = (Number(e.target.value) === 6 ? 6 : 3) as 3 | 6;
            const autoLimit = calcCandleLimit(months, config.strategy_mode);
            setPeriodMonths(months);
            setCandleLimit(autoLimit);
            saveBacktestConfig({ backtest_period_months: months, backtest_candle_limit: autoLimit });
          }}>
            <option value={3}>최근 3개월</option><option value={6}>최근 6개월</option>
          </select>
        </label>
        <label>캔들
          <input type="number" min={80} max={60000} step={10} value={candleLimit} onChange={(e) => {
            if (e.target.value === "") { setCandleLimit(""); onPatchConfig?.({ backtest_candle_limit: "" as unknown as number }); return; }
            const n = Math.max(80, Math.min(60000, Number(e.target.value))); setCandleLimit(n); saveBacktestConfig({ backtest_candle_limit: n });
          }} />
          {candleLimit ? <span style={{ fontSize: "0.75em", color: "#aaa", marginLeft: 4 }}>{candleDesc(Number(candleLimit), config.strategy_mode)}</span> : null}
        </label>
        <label>자동 주기(분)
          <input type="number" min={1} step={1} value={intervalInput} onChange={(e) => {
            if (e.target.value === "") { setIntervalInput(""); onPatchConfig?.({ backtest_interval_minutes: "" as unknown as number }); return; }
            const n = Math.max(1, Number(e.target.value)); setIntervalInput(n); saveBacktestConfig({ backtest_interval_minutes: n });
          }} />
        </label>
        <label><input type="checkbox" checked={optimize} onChange={(e) => setOptimize(e.target.checked)} />min_score 자동 탐색</label>
      </div>
      <div className="bt-auto-hint">서버 시작 시 자동 백테스트 {bundle?.auto_run ? "ON" : "OFF"} · 주기 {bundle?.interval_minutes ?? config.backtest_interval_minutes ?? 60}분 · 기간 {periodMonths}개월 · 보호 익절 설정까지 추천/반영</div>
      {displayMessage && <div className="bt-msg">{status?.running ? `진행 ${status.progress_pct}% · ${phaseLabel(status.phase)} · ` : ""}{displayMessage}</div>}
      <MetricsCards result={result} />
      <Recommendation result={result} config={config} />
      <ZoneWalkForward result={result} />
      {result && <BacktestCandlesGrid result={result} />}
      <TradesTable result={result} />
      <SymbolProfiles profiles={profiles} />
      {!!result?.logs?.length && <div className="section"><h2>백테스트 로그</h2><div className="bt-log-scroll">{result.logs.slice(-80).map((l, idx) => <div key={`${l.ts}-${idx}`}>{formatKstTime(l.ts, true)} [{l.level}] {l.message}</div>)}</div></div>}
      {!!bundle?.auto_apply_history?.length && (
        <div className="section">
          <h2>자동 적용 이력</h2>
          <div className="bt-scroll">
            <table>
              <thead>
                <tr>
                  <th>시각</th>
                  <th>결과</th>
                  <th>사유</th>
                  <th>전</th>
                  <th>후</th>
                </tr>
              </thead>
              <tbody>
                {bundle.auto_apply_history.slice(0, 20).map((a, idx) => (
                  <tr key={`${a.ts}-${idx}`}>
                    <td>{formatKstTime(a.ts, true)}</td>
                    <td className={a.accepted ? "green" : "red"}>{a.accepted ? "적용" : "보류"}</td>
                    <td>{a.reason}</td>
                    <td>
                      {a.before
                        ? `${a.before.min_score} · SL ${fmtPct(a.before.stop_loss_pct)} / TP ${fmtPct(a.before.take_profit_pct)} · 보호 ${fmtPct(a.before.profit_protect_trigger_pct)}`
                        : "-"}
                    </td>
                    <td>
                      {a.after
                        ? `${a.after.min_score} · SL ${fmtPct(a.after.stop_loss_pct)} / TP ${fmtPct(a.after.take_profit_pct)} · 보호 ${fmtPct(a.after.profit_protect_trigger_pct)}`
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <HistoryTable history={bundle?.history} />
    </div>
  );
}
