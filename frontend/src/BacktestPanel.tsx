import { useCallback, useEffect, useRef, useState } from "react";
import { applyBacktest, fetchBacktestStatus, runBacktest, updateConfig } from "./api";
import { BacktestCandlesGrid, TradeMiniCandle } from "./BacktestCandles";
import { fmtNum } from "./format";
import type { AppConfig, BacktestBundle } from "./types";

export function BacktestPanel({
  config,
  bundle,
  onRefresh,
  onConfigApplied,
  onPatchConfig,
}: {
  config: AppConfig;
  bundle: BacktestBundle | null | undefined;
  onRefresh: () => void;
  onConfigApplied: (minScore: number) => void;
  onPatchConfig: (patch: Partial<AppConfig>) => void;
}) {
  const [running, setRunning] = useState(bundle?.status?.running ?? false);
  const [msg, setMsg] = useState("");
  const [candleLimit, setCandleLimit] = useState(200);
  const [optimize, setOptimize] = useState(true);
  const intervalMin =
    bundle?.interval_minutes ?? config.backtest_interval_minutes ?? 60;
  const saveIntervalRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleIntervalSave = useCallback(
    (minutes: number) => {
      onPatchConfig({ backtest_interval_minutes: minutes });
      if (saveIntervalRef.current) clearTimeout(saveIntervalRef.current);
      saveIntervalRef.current = setTimeout(async () => {
        await updateConfig({ ...config, backtest_interval_minutes: minutes });
        onRefresh();
      }, 400);
    },
    [config, onPatchConfig, onRefresh],
  );

  useEffect(
    () => () => {
      if (saveIntervalRef.current) clearTimeout(saveIntervalRef.current);
    },
    [],
  );

  const result = bundle?.result ?? null;
  const status = bundle?.status;

  useEffect(() => {
    setRunning(status?.running ?? false);
  }, [status?.running]);

  useEffect(() => {
    if (!running) return;
    const iv = setInterval(async () => {
      await fetchBacktestStatus().then(() => onRefresh());
    }, 2500);
    return () => clearInterval(iv);
  }, [running, onRefresh]);

  const handleRun = useCallback(async () => {
    setMsg("시작 중…");
    const res = await runBacktest({
      symbols: config.scan_symbols?.slice(0, 8) ?? [],
      candle_limit: candleLimit,
      optimize,
    });
    setMsg(res.message || (res.ok ? "실행 중" : "실패"));
    if (res.ok) setRunning(true);
    onRefresh();
  }, [config.scan_symbols, candleLimit, optimize, onRefresh]);

  const handleApply = useCallback(async () => {
    const res = await applyBacktest();
    if (!res.ok) {
      setMsg(res.message || "적용 실패");
      return;
    }
    setMsg(res.message || "적용됨");
    if (res.min_score != null) onConfigApplied(res.min_score);
    onRefresh();
  }, [onConfigApplied, onRefresh]);

  const rec = result?.recommendation;
  const m = result?.metrics;

  return (
    <div className="backtest-panel">
      <div className="backtest-toolbar">
        <button type="button" className="primary" disabled={running} onClick={handleRun}>
          {running ? "백테스트 실행 중…" : "백테스트 실행"}
        </button>
        <button
          type="button"
          disabled={!rec || running || !!config.backtest_auto_settings}
          onClick={handleApply}
          title={
            config.backtest_auto_settings
              ? "설정에서 백테스트 유동 설정(자동)이 켜져 있음"
              : "추천 min_score를 설정에 반영"
          }
        >
          추천 점수 설정 적용
        </button>
        <label>
          캔들
          <input
            type="number"
            min={80}
            max={300}
            value={candleLimit}
            onChange={(e) => setCandleLimit(Number(e.target.value))}
          />
        </label>
        <label className="chk">
          <input
            type="checkbox"
            checked={optimize}
            onChange={(e) => setOptimize(e.target.checked)}
          />
          min_score 자동 탐색
        </label>
        <label>
          자동 주기(분)
          <input
            type="number"
            min={1}
            max={1440}
            value={intervalMin}
            onChange={(e) => {
              const v = Math.max(1, Math.min(1440, Number(e.target.value) || 60));
              scheduleIntervalSave(v);
            }}
            title="서버 켜지면 바로 시작, 완료 후 이 간격으로 무한 반복"
          />
        </label>
        {status && (
          <span className="bt-progress">
            {status.phase} {status.progress_pct > 0 ? `${fmtNum(status.progress_pct, 0)}%` : ""}
            {status.message ? ` — ${status.message}` : ""}
          </span>
        )}
      </div>
      {msg && <p className="bt-msg">{msg}</p>}

      <p className="bt-auto-hint">
        {bundle?.auto_run !== false
          ? `서버 시작 시 자동 백테스트 → 완료 후 ${intervalMin}분마다 무한 반복 (버튼 불필요) · backend/data/backtest_history.jsonl`
          : "자동 백테스트 꺼짐 (.env OAT_BACKTEST_AUTO_RUN=1)"}
        {config.backtest_auto_settings && (
          <>
            <br />
            <strong style={{ color: "#3fb950" }}>
              유동 설정 ON — 완료 시 min_score·가용% 주문이 자동 반영되어 매매합니다.
            </strong>
          </>
        )}
      </p>

      {(bundle?.history?.length ?? 0) > 0 && (
        <div className="section">
          <h2>실행 이력 ({bundle?.history?.length})</h2>
          <table>
            <thead>
              <tr>
                <th>시각</th>
                <th>상태</th>
                <th>PnL</th>
                <th>거래</th>
                <th>추천 score</th>
              </tr>
            </thead>
            <tbody>
              {bundle?.history?.map((h) => (
                <tr key={h.id}>
                  <td className="ts-cell">{h.finished_at?.slice(0, 19).replace("T", " ")}</td>
                  <td>{h.status}</td>
                  <td className={(h.metrics?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}>
                    {h.metrics?.total_pnl != null
                      ? `${h.metrics.total_pnl >= 0 ? "+" : ""}${fmtNum(h.metrics.total_pnl)}`
                      : "—"}
                  </td>
                  <td>{h.trade_count}</td>
                  <td>{h.recommendation?.min_score ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result && (
        <>
          <div className="grid backtest-summary">
            <div className="card">
              <h3>총 손익</h3>
              <div className={`value ${(m?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}`}>
                {(m?.total_pnl ?? 0) >= 0 ? "+" : ""}{fmtNum(m?.total_pnl ?? 0)} USDT
              </div>
              <div className="sub">({fmtNum(m?.total_pnl_pct ?? 0, 1)}%)</div>
            </div>
            <div className="card">
              <h3>거래 / 승률</h3>
              <div className="value">{m?.trade_count ?? 0}건</div>
              <div className="sub">승률 {fmtNum(m?.win_rate ?? 0, 1)}%</div>
            </div>
            <div className="card">
              <h3>롱 / 숏</h3>
              <div className="value">
                {m?.long_trades ?? 0} / {m?.short_trades ?? 0}
              </div>
              <div className="sub">평균 진입 점수 {fmtNum(m?.avg_score_entries ?? 0, 1)}</div>
            </div>
            <div className="card">
              <h3>추천 min_score</h3>
              <div className="value">{rec?.min_score ?? "—"}</div>
              <div className="sub">{rec?.reason ?? "탐색 안 함"}</div>
            </div>
          </div>

          <BacktestCandlesGrid result={result} />

          {rec?.trials && rec.trials.length > 0 && (
            <div className="section">
              <h2>점수별 탐색 결과</h2>
              <table>
                <thead>
                  <tr>
                    <th>min_score</th>
                    <th>PnL</th>
                    <th>승률</th>
                    <th>거래</th>
                    <th>롱</th>
                    <th>숏</th>
                  </tr>
                </thead>
                <tbody>
                  {rec.trials.map((t) => (
                    <tr
                      key={t.min_score}
                      className={t.min_score === rec.min_score ? "row-best" : ""}
                    >
                      <td><strong>{t.min_score}</strong></td>
                      <td className={t.total_pnl >= 0 ? "positive" : "negative"}>
                        {t.total_pnl >= 0 ? "+" : ""}{fmtNum(t.total_pnl)}
                      </td>
                      <td>{fmtNum(t.win_rate, 1)}%</td>
                      <td>{t.trades}</td>
                      <td>{t.long_entries}</td>
                      <td>{t.short_entries}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="section bt-split">
            <div className="bt-col">
              <h2>백테스트 거래 ({result.trades?.length ?? 0})</h2>
              <div className="bt-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>캔들</th>
                      <th>종목</th>
                      <th>방향</th>
                      <th>점수</th>
                      <th>진입</th>
                      <th>청산</th>
                      <th>PnL</th>
                      <th>사유</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.trades ?? []).map((t, i) => (
                      <tr key={`${t.inst_id}-${i}`}>
                        <td className="chart-col">
                          <TradeMiniCandle
                            instId={t.inst_id}
                            entryBar={t.entry_bar}
                            exitBar={t.exit_bar}
                            charts={result.symbol_charts}
                          />
                        </td>
                        <td>{t.inst_id}</td>
                        <td><span className={`badge ${t.side}`}>{t.side.toUpperCase()}</span></td>
                        <td>{fmtNum(t.score, 0)}</td>
                        <td>{fmtNum(t.entry_price, 4)}</td>
                        <td>{fmtNum(t.exit_price, 4)}</td>
                        <td className={t.pnl_usdt >= 0 ? "positive" : "negative"}>
                          {t.pnl_usdt >= 0 ? "+" : ""}{fmtNum(t.pnl_usdt)}
                        </td>
                        <td style={{ fontSize: "0.75rem" }}>{t.exit_reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="bt-col">
              <h2>세부 로그</h2>
              <div className="bt-log-scroll">
                {(result.logs ?? []).map((log, i) => (
                  <div key={i} className={`log-entry ${log.level}`}>
                    <span className="ts">{log.ts?.slice(11, 19)}</span>
                    {log.message}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <p className="bt-note">
            적용 파라미터: min_score={String(result.params_snapshot?.min_score_applied ?? "—")}
            · 현재 설정 {config.min_score}
            · {result.symbols?.join(", ")}
          </p>
        </>
      )}

      {!result && !running && (
        <p style={{ color: "#8b949e", marginTop: 16 }}>
          OKX 캔들(최대 300봉)로 과거 시뮬레이션 후 min_score·롱/숏 진입을 추천합니다.
          실행 후 「추천 점수 설정 적용」으로 라이브 설정에 반영하세요.
        </p>
      )}
    </div>
  );
}
