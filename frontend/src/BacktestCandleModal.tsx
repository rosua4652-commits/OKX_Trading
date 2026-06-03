import { useEffect } from "react";
import { MiniCandles, type OhlcBar } from "./CandleChart";
import type { SymbolCandleChart } from "./types";

export function BacktestCandleModal({
  instId,
  chart,
  interval,
  onClose,
}: {
  instId: string;
  chart: SymbolCandleChart;
  interval?: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const bars: OhlcBar[] = (chart.bars ?? []).map((b) => ({
    o: b.o,
    h: b.h,
    l: b.l,
    c: b.c,
  }));

  return (
    <div className="chart-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="chart-modal bt-candle-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`${instId} 백테스트 캔들`}
      >
        <div className="chart-modal-header">
          <div>
            <h2>{instId}</h2>
            <span className="chart-modal-sub">
              {interval ?? "5m"} · 파랑=진입 · 노랑=청산
            </span>
          </div>
          <button type="button" className="chart-modal-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="bt-candle-modal-body">
          <MiniCandles
            bars={bars}
            markers={chart.trade_markers}
            width={560}
            height={220}
          />
          <p className="bt-candle-sub">
            전체 {chart.total_bars}봉
            {chart.display_offset > 0 ? ` · 표시 구간 ${chart.display_offset}~` : ""}
            {chart.trade_markers?.length
              ? ` · 거래 마커 ${chart.trade_markers.length}건`
              : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
