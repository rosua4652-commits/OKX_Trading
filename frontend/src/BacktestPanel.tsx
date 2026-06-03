import { useCallback, useEffect, useRef, useState } from "react";
import { applyBacktest, fetchBacktestStatus, runBacktest, updateConfig } from "./api";
import { BacktestCandlesGrid, TradeMiniCandle } from "./BacktestCandles";
import { fmtNum, fmtPrice, fmtUsd } from "./format";
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
    if (res.config) onPatchConfig(res.config);
    else if (res.min_score != null) onConfigApplied(res.min_score);
    onRefresh();
  }, [onConfigApplied, onPatchConfig, onRefresh]);

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
          disabled={
            !rec ||
            running ||
            !!(config.backtest_auto_settings && config.backtest_auto_sl_tp)
          }
          onClick={handleApply}
          title={
            config.backtest_auto_settings && config.backtest_auto_sl_tp
              ? "설정에서 백테스트 자동(점수·SL/TP)이 모두 켜져 있음"
              : config.backtest_auto_settings
                ? "min_score는 자동 적용 중 — SL/TP만 수동 적용하려면 점수 자동을 끄세요"
                : config.backtest_auto_sl_tp
                  ? "SL/TP는 자동 적용 중 — 점수만 수동 적용하려면 SL/TP 자동을 끄세요"
                  : "추천 min_score·SL/TP를 설정에 반영"
          }
        >
          추천 설정 적용
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
              유동 설정 ON — 완료 시 min_score만 자동 반영 (주문 크기는 설정 화면 값 유지).
            </strong>
          </>
        )}
        {config.backtest_auto_sl_tp && (
          <>
            <br />
            <strong style={{ color: "#58a6ff" }}>
              SL/TP 자동 ON — 종목별 백테스트 프로필이 자동매매 진입 SL/TP에 적용됩니다.
            </strong>
          </>
        )}
      </p>

      {(bundle?.symbol_profiles?.length ?? 0) > 0 && (
        <div className="section">
          <h2>종목별 SL/TP 프로필 (자동매매 적용)</h2>
          <div className="bt-dir-scroll">
            <table>
              <thead>
                <tr>
                  <th>종목</th>
                  <th>SL%</th>
                  <th>TP%</th>
                  <th>승률</th>
                  <th>거래</th>
                  <th>익절평균</th>
                </tr>
              </thead>
              <tbody>
                {(bundle?.symbol_profiles ?? [])
                  .sort((a, b) => b.win_rate - a.win_rate)
                  .map((p) => (
                    <tr key={p.inst_id}>
                      <td>{p.inst_id}</td>
                      <td>{fmtNum(p.stop_loss_pct, 1)}</td>
                      <td><strong>{fmtNum(p.take_profit_pct, 1)}</strong></td>
                      <td>{fmtNum(p.win_rate, 1)}%</td>
                      <td>{p.trades}</td>
                      <td>
                        {p.avg_win_tp_pct && p.avg_win_tp_pct > 0
                          ? `${fmtNum(p.avg_win_tp_pct, 1)}%`
                          : "—"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(bundle?.history?.length ?? 0) > 0 && (
        <div className="section">
          <h2>실행 이력 ({bundle?.history?.length})</h2>
          <table>
            <thead>
              <tr>
                <th>시각</th>
                <th>상태</th>
                <th>종목</th>
                <th>방향</th>
                <th>PnL</th>
                <th>승률</th>
                <th>거래</th>
                <th>추천</th>
                <th>SL/TP</th>
              </tr>
            </thead>
            <tbody>
              {bundle?.history?.map((h) => (
                <tr key={`${h.id}-${h.finished_at}`}>
                  <td className="ts-cell">{h.finished_at?.slice(0, 19).replace("T", " ")}</td>
                  <td title={h.error || undefined}>
                    {h.status}
                    {h.status === "error" && h.error ? (
                      <span className="bt-err-hint" title={h.error}>
                        {" "}
                        ({h.error.length > 40 ? `${h.error.slice(0, 40)}…` : h.error})
                      </span>
                    ) : null}
                  </td>
                  <td className="sym-cell" title={(h.symbols ?? []).join(", ")}>
                    {(h.symbols ?? []).join(", ") || "—"}
                  </td>
                  <td>
                    {h.direction === "inverse" ? "역방향" : h.direction === "normal" ? "정방향" : "—"}
                    {h.window_ratio != null && h.window_ratio < 1
                      ? ` ${Math.round(h.window_ratio * 100)}%`
                      : ""}
                  </td>
                  <td className={(h.metrics?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}>
                    {h.metrics?.total_pnl != null
                      ? `${h.metrics.total_pnl >= 0 ? "+" : ""}${fmtNum(h.metrics.total_pnl)}`
                      : "—"}
                  </td>
                  <td>
                    {h.metrics?.win_rate != null ? `${fmtNum(h.metrics.win_rate, 1)}%` : "—"}
                  </td>
                  <td>{h.trade_count}</td>
                  <td>{h.recommendation?.min_score ?? "—"}</td>
                  <td>
                    {h.recommendation?.stop_loss_pct != null
                      ? `${fmtNum(h.recommendation.stop_loss_pct, 1)}/${fmtNum(h.recommendation.take_profit_pct ?? 0, 1)}%`
                      : h.applied_sl_pct != null
                        ? `${fmtNum(h.applied_sl_pct, 1)}/${fmtNum(h.applied_tp_pct ?? 0, 1)}%`
                        : "—"}
                  </td>
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
              <h3>시작 / 최종 자산</h3>
              <div className="value" style={{ fontSize: "1rem" }}>
                ${fmtNum(Number(m?.start_equity ?? result.params_snapshot?.start_equity ?? 0), 0)}
                {" → "}
                ${fmtNum(m?.end_equity ?? 0, 0)}
              </div>
              <div className="sub">USD (모의 초기자금 · USDT-M ≈ USD)</div>
            </div>
            <div className="card">
              <h3>총 손익</h3>
              <div className={`value ${(m?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}`}>
                {(m?.total_pnl ?? 0) >= 0 ? "+" : ""}{fmtUsd(m?.total_pnl ?? 0, 2)}
              </div>
              <div className="sub">
                ({fmtNum(m?.total_pnl_pct ?? 0, 2)}%)
                {(m?.total_fees_usdt ?? 0) > 0
                  ? ` · 수수료 ${fmtNum(m?.total_fees_usdt ?? 0)}`
                  : ""}
              </div>
            </div>
            <div className="card">
              <h3>1회 투입 (명목)</h3>
              <div className="value">
                ${fmtNum(Number(m?.order_notional_usdt ?? result.params_snapshot?.order_notional_usdt ?? 0), 0)}
              </div>
              <div className="sub">
                증거금 ≈ $
                {fmtNum(
                  (m?.order_notional_usdt ?? 0) /
                    Math.max(1, Number(result.params_snapshot?.leverage ?? 10)),
                  0,
                )}{" "}
                (레버 {String(result.params_snapshot?.leverage ?? "—")}x)
              </div>
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
            <div className="card">
              <h3>추천 SL / TP</h3>
              <div className="value">
                {rec?.stop_loss_pct != null && rec?.take_profit_pct != null
                  ? `${fmtNum(rec.stop_loss_pct, 1)}% / ${fmtNum(rec.take_profit_pct, 1)}%`
                  : "—"}
              </div>
              <div className="sub">{rec?.sl_tp_reason ?? "SL/TP 탐색 안 함"}</div>
            </div>
            <div className="card bt-direction-card">
              <h3>추천 방향</h3>
              <div className="value">
                {rec?.direction === "inverse" ? "역방향 (신호 반전)" : "정방향"}
              </div>
              <div className="sub">
                구간 {Math.round((rec?.window_ratio ?? 1) * 100)}%
                {result.symbols?.length ? ` · ${result.symbols.join(", ")}` : ""}
              </div>
            </div>
          </div>

          <BacktestCandlesGrid result={result} />

          {rec?.direction_trials && rec.direction_trials.length > 0 && (
            <div className="section">
              <h2>방향·구간 탐색 ({rec.direction_trials.length}조합)</h2>
              <div className="bt-dir-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>방향</th>
                      <th>구간</th>
                      <th>score</th>
                      <th>PnL</th>
                      <th>승률</th>
                      <th>거래</th>
                      <th>롱/숏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rec.direction_trials
                      .filter((t) => t.trades > 0)
                      .sort(
                        (a, b) =>
                          b.total_pnl + b.win_rate * 0.35 - (a.total_pnl + a.win_rate * 0.35),
                      )
                      .slice(0, 24)
                      .map((t, i) => (
                        <tr
                          key={`${t.mode}-${t.window_ratio}-${t.min_score}-${i}`}
                          className={
                            t.mode === rec.direction &&
                            t.window_ratio === rec.window_ratio &&
                            t.min_score === rec.min_score
                              ? "row-best"
                              : ""
                          }
                        >
                          <td>{t.mode === "inverse" ? "역방향" : "정방향"}</td>
                          <td>{Math.round(t.window_ratio * 100)}%</td>
                          <td>{t.min_score}</td>
                          <td className={t.total_pnl >= 0 ? "positive" : "negative"}>
                            {t.total_pnl >= 0 ? "+" : ""}{fmtNum(t.total_pnl)}
                          </td>
                          <td>{fmtNum(t.win_rate, 1)}%</td>
                          <td>{t.trades}</td>
                          <td>
                            {t.long_trades ?? 0}/{t.short_trades ?? 0}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {rec?.sl_tp_trials && rec.sl_tp_trials.length > 0 && (
            <div className="section">
              <h2>SL/TP 탐색 (승률 우선, {rec.sl_tp_trials.length}조합)</h2>
              <div className="bt-dir-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>SL%</th>
                      <th>TP%</th>
                      <th>승률</th>
                      <th>PnL</th>
                      <th>거래</th>
                      <th>익절</th>
                      <th>손절</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rec.sl_tp_trials
                      .filter((t) => t.trades > 0)
                      .sort(
                        (a, b) =>
                          b.win_rate + b.total_pnl * 0.05 - (a.win_rate + a.total_pnl * 0.05),
                      )
                      .slice(0, 20)
                      .map((t, i) => (
                        <tr
                          key={`${t.stop_loss_pct}-${t.take_profit_pct}-${i}`}
                          className={
                            t.stop_loss_pct === rec.stop_loss_pct &&
                            t.take_profit_pct === rec.take_profit_pct
                              ? "row-best"
                              : ""
                          }
                        >
                          <td>{fmtNum(t.stop_loss_pct, 1)}</td>
                          <td>{fmtNum(t.take_profit_pct, 1)}</td>
                          <td>{fmtNum(t.win_rate, 1)}%</td>
                          <td className={t.total_pnl >= 0 ? "positive" : "negative"}>
                            {t.total_pnl >= 0 ? "+" : ""}{fmtNum(t.total_pnl)}
                          </td>
                          <td>{t.trades}</td>
                          <td>{t.tp_hits ?? 0}</td>
                          <td>{t.sl_hits ?? 0}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

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
                      <th>투입(명목)</th>
                      <th>증거금</th>
                      <th>진입</th>
                      <th>청산</th>
                      <th>손익</th>
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
                        <td>${fmtNum(t.notional_usdt ?? 0, 0)}</td>
                        <td className="muted">${fmtNum(t.margin_usdt ?? 0, 0)}</td>
                        <td>{fmtPrice(t.entry_price)}</td>
                        <td>{fmtPrice(t.exit_price)}</td>
                        <td className={t.pnl_usdt >= 0 ? "positive" : "negative"}>
                          {t.pnl_usdt >= 0 ? "+" : ""}{fmtUsd(t.pnl_usdt, 2)}
                          <span className="muted" style={{ fontSize: "0.7rem" }}>
                            {" "}({t.pnl_usdt >= 0 ? "+" : ""}{fmtNum(t.pnl_pct, 2)}%)
                          </span>
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
            시작 ${String(result.params_snapshot?.start_equity ?? m?.start_equity ?? "—")} →
            최종 ${String(m?.end_equity ?? "—")} ·
            1회 명목 ${String(result.params_snapshot?.order_notional_usdt ?? m?.order_notional_usdt ?? "—")} ·
            적용 min_score={String(result.params_snapshot?.min_score_applied ?? "—")}
            · SL/TP {String(result.params_snapshot?.stop_loss_pct_applied ?? "—")}/
            {String(result.params_snapshot?.take_profit_pct_applied ?? "—")}%
            · 방향 {String(result.params_snapshot?.direction ?? "normal")}
            · 구간 {Math.round(Number(result.params_snapshot?.window_ratio ?? 1) * 100)}%
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
