import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CandleChart, type ChartLevels } from "./CandleChart";
import { fmtNum, fmtPnlUsdt, fmtPrice } from "./format";
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

function defaultModalSize() {
  return {
    w: Math.min(1100, Math.round(window.innerWidth * 0.92)),
    h: Math.min(780, Math.round(window.innerHeight * 0.88)),
  };
}

function crossedLevel(p: Position) {
  const isShort = p.side === "short";
  const hitTp =
    p.take_profit > 0 &&
    (isShort ? p.current_price <= p.take_profit : p.current_price >= p.take_profit);
  const hitSl =
    p.stop_loss > 0 &&
    (isShort ? p.current_price >= p.stop_loss : p.current_price <= p.stop_loss);
  return { hitTp, hitSl };
}

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
  const modalRef = useRef<HTMLDivElement>(null);
  const [chartHeight, setChartHeight] = useState(420);
  const [modalSize, setModalSize] = useState(defaultModalSize);
  const resizingRef = useRef(false);

  useEffect(() => {
    if (target) setTab("oat");
  }, [target?.instId]);

  useEffect(() => {
    if (target) setModalSize(defaultModalSize());
  }, [target?.instId]);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !target) return;
    const update = () => setChartHeight(Math.max(260, el.clientHeight - 4));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [target?.instId, tab, modalSize]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleBackdropMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (resizingRef.current) return;
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  const handleResizeStart = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      resizingRef.current = true;
      const startX = e.clientX;
      const startY = e.clientY;
      const startW = modalSize.w;
      const startH = modalSize.h;

      const onMove = (ev: PointerEvent) => {
        setModalSize({
          w: Math.min(
            window.innerWidth * 0.98,
            Math.max(520, startW + ev.clientX - startX),
          ),
          h: Math.min(
            window.innerHeight * 0.96,
            Math.max(480, startH + ev.clientY - startY),
          ),
        });
      };

      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.setTimeout(() => {
          resizingRef.current = false;
        }, 0);
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [modalSize.h, modalSize.w],
  );

  const p = target?.position;
  const crossed = useMemo(() => (p ? crossedLevel(p) : { hitTp: false, hitSl: false }), [p]);

  if (!target) return null;

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
          p.leverage && p.leverage > 0 ? p.leverage : configLeverage,
          p.instrument_type || "swap",
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
          leverage: p.leverage && p.leverage > 0 ? p.leverage : configLeverage,
          instrumentType: p.instrument_type || "swap",
          entryTime: p.opened_at,
        };
      })()
    : {});

  return (
    <div
      className="chart-modal-backdrop"
      onMouseDown={handleBackdropMouseDown}
      role="presentation"
    >
      <div
        ref={modalRef}
        className="chart-modal chart-modal-resizable"
        style={{ width: modalSize.w, height: modalSize.h }}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="chart-modal-header">
          <div>
            <h2>{target.title}</h2>
            <span className="chart-modal-sub">
              {target.instId} · {strategyToBarLabel(target.strategy)}
            </span>
          </div>
          <button type="button" className="chart-modal-close" onClick={onClose}>
            닫기
          </button>
        </div>

        {p && (
          <div className="chart-position-banner">
            <span className={`badge ${p.side}`}>{p.side.toUpperCase()}</span>
            <span>진입 ${fmtPrice(p.entry_price)}</span>
            <span>현재 ${fmtPrice(p.current_price)}</span>
            <span className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>
              PnL {p.unrealized_pnl >= 0 ? "+" : ""}{fmtPnlUsdt(p.unrealized_pnl)} USDT
            </span>
            <span className={p.unrealized_pnl_pct >= 0 ? "positive" : "negative"}>
              PnL ROI {p.unrealized_pnl_pct >= 0 ? "+" : ""}{fmtNum(p.unrealized_pnl_pct, 1)}%
            </span>
            {p.instrument_type !== "spot" && (
              <span>레버 {(p.leverage && p.leverage > 0 ? p.leverage : configLeverage)}x</span>
            )}
            <span className="muted">SL ${fmtPrice(p.stop_loss)} · TP ${fmtPrice(p.take_profit)}</span>
            {p.auto_sl_tp_disabled && (
              <span className="chart-auto-off">
                자동 OFF{(crossed.hitTp || crossed.hitSl) ? ` · ${crossed.hitTp ? "익절선" : "손절선"} 통과` : ""}
              </span>
            )}
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
        <div
          className="chart-modal-resize-handle"
          onPointerDown={handleResizeStart}
          title="드래그해서 크기 조절"
        >
          크기
        </div>
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
