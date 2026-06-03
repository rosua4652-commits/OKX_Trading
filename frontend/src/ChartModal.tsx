import { useEffect, useRef, useState } from "react";
import { CandleChart, type ChartLevels } from "./CandleChart";
import { fmtNum, fmtPrice } from "./format";
import { slTpFromPrices } from "./format";
import { strategyToBarLabel } from "./chartSymbols";
import { slTpPctForStrategy } from "./strategy";
import { TradingViewChart } from "./TradingViewChart";
import type { Position } from "./types";

export type ChartViewTarget = {
  instId: string;
  strategy: string;
  title: string;
  levels?: ChartLevels;
  position?: Position;
};

export function ChartModal({
  target,
  onClose,
  configLeverage = 3,
}: {
  target: ChartViewTarget | null;
  onClose: () => void;
  configLeverage?: number;
}) {
  const [tab, setTab] = useState<"oat" | "tv">("oat");
  const bodyRef = useRef<HTMLDivElement>(null);
  const [chartHeight, setChartHeight] = useState(420);

  useEffect(() => {
    if (target) setTab(target.position ? "oat" : "oat");
  }, [target?.instId]);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !target) return;
    const update = () => setChartHeight(Math.max(260, el.clientHeight - 4));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [target?.instId, tab]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!target) return null;

  const p = target.position;
  const chartStrat = p?.strategy_mode && p.strategy_mode !== "both"
    ? p.strategy_mode
    : target.strategy;
  const defaultPct = slTpPctForStrategy(chartStrat);
  const levels: ChartLevels = target.levels ?? (p
    ? (() => {
        const fromPrices = slTpFromPrices(
          p.entry_price,
          p.stop_loss,
          p.take_profit,
          p.side,
        );
        return {
          entry: p.entry_price,
          stopLoss: p.stop_loss,
          takeProfit: p.take_profit,
          side: p.side,
          slPct: p.sl_pct && p.sl_pct > 0 ? p.sl_pct : Math.round(fromPrices.slPct * 10) / 10 || defaultPct.sl,
          tpPct: p.tp_pct && p.tp_pct > 0 ? p.tp_pct : Math.round(fromPrices.tpPct * 10) / 10 || defaultPct.tp,
          currentPrice: p.current_price,
          unrealizedPnl: p.unrealized_pnl,
          unrealizedPnlPct: p.unrealized_pnl_pct,
          entryTime: p.opened_at,
        };
      })()
    : {});

  return (
    <div className="chart-modal-backdrop" onClick={onClose}>
      <div
        className="chart-modal chart-modal-resizable"
        onClick={(e) => e.stopPropagation()}
        title="우하단 모서리를 드래그해 크기 조절"
      >
        <div className="chart-modal-header">
          <div>
            <h2>{target.title}</h2>
            <span className="chart-modal-sub">{target.instId} · {strategyToBarLabel(target.strategy)}</span>
          </div>
          <button type="button" className="chart-modal-close" onClick={onClose}>
            ✕
          </button>
        </div>

        {p && (
          <div className="chart-position-banner">
            <span className={`badge ${p.side}`}>{p.side.toUpperCase()}</span>
            <span>진입 ${fmtPrice(p.entry_price)}</span>
            <span>현재 ${fmtPrice(p.current_price)}</span>
            <span className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>
              PnL {p.unrealized_pnl >= 0 ? "+" : ""}{fmtNum(p.unrealized_pnl)} ({fmtNum(p.unrealized_pnl_pct, 1)}%)
            </span>
            {p.instrument_type !== "spot" && (
              <span>
                레버 {(p.leverage && p.leverage > 0 ? p.leverage : configLeverage)}x
              </span>
            )}
            <span className="muted">SL ${fmtPrice(p.stop_loss)} · TP ${fmtPrice(p.take_profit)}</span>
          </div>
        )}

        <div className="chart-tabs">
          <button
            type="button"
            className={tab === "oat" ? "active" : ""}
            onClick={() => setTab("oat")}
          >
            OKX 트레이딩 차트
          </button>
          <button
            type="button"
            className={tab === "tv" ? "active" : ""}
            onClick={() => setTab("tv")}
          >
            TradingView (그리기·지표)
          </button>
        </div>

        <div className="chart-modal-body" ref={bodyRef}>
          {tab === "oat" ? (
            <CandleChart
              instId={target.instId}
              strategy={chartStrat}
              height={chartHeight}
              levels={levels}
              pro
            />
          ) : (
            <TradingViewChart instId={target.instId} strategy={chartStrat} height={chartHeight} />
          )}
        </div>
        <span className="chart-modal-resize-hint">↘ 크기 조절</span>
      </div>
    </div>
  );
}

export function buildPositionChartTarget(p: Position, strategy: string): ChartViewTarget {
  return {
    instId: p.inst_id,
    strategy: p.strategy_mode || strategy,
    title: `포지션 · ${p.inst_id}`,
    position: p,
  };
}

export function buildCandidateChartTarget(
  instId: string,
  strategy: string,
  levels?: ChartLevels,
): ChartViewTarget {
  return {
    instId,
    strategy,
    title: `분석 · ${instId}`,
    levels,
  };
}
