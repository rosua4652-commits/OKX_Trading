import { MiniCandles, type OhlcBar } from "./CandleChart";
import type { BacktestResult, SymbolCandleChart } from "./types";

function chartToBars(chart: SymbolCandleChart): OhlcBar[] {
  return (chart.bars ?? []).map((b) => ({
    o: b.o,
    h: b.h,
    l: b.l,
    c: b.c,
  }));
}

export function BacktestCandlesGrid({ result }: { result: BacktestResult }) {
  const charts = result.symbol_charts ?? {};
  const keys = Object.keys(charts);
  if (!keys.length) return null;

  return (
    <div className="section bt-candles-section">
      <h2>
        백테스트 캔들
        <span className="bt-candles-meta">
          {result.candle_interval ?? "5m"} · 최근 봉 미리보기 · 파랑=진입 · 노랑=청산
        </span>
      </h2>
      <div className="bt-candles-grid">
        {keys.map((instId) => {
          const ch = charts[instId];
          const bars = chartToBars(ch);
          return (
            <div key={instId} className="bt-candle-card">
              <div className="bt-candle-title">{instId}</div>
              <MiniCandles
                bars={bars}
                markers={ch.trade_markers}
                width={140}
                height={44}
              />
              <div className="bt-candle-sub">
                전체 {ch.total_bars}봉
                {ch.display_offset > 0 ? ` · 표시 ${ch.display_offset}~` : ""}
                {ch.trade_markers?.length ? ` · 거래 ${ch.trade_markers.length}` : ""}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TradeMiniCandle({
  instId,
  entryBar,
  exitBar,
  charts,
}: {
  instId: string;
  entryBar: number;
  exitBar: number;
  charts?: Record<string, SymbolCandleChart>;
}) {
  const ch = charts?.[instId];
  if (!ch?.bars?.length) return <span className="sparkline-empty">—</span>;

  const offset = ch.display_offset ?? 0;
  const window = 24;
  const center = Math.max(entryBar, exitBar);
  let start = Math.max(offset, center - window);
  let end = Math.min(ch.total_bars ?? offset + ch.bars.length, center + 8);
  if (end - start < 12) end = Math.min(ch.total_bars, start + 12);

  const relStart = start - offset;
  const relEnd = end - offset;
  const slice = ch.bars.slice(
    Math.max(0, relStart),
    Math.min(ch.bars.length, relEnd),
  ) as OhlcBar[];

  const markers = [
    {
      entry: entryBar - start,
      exit: exitBar >= start && exitBar < end ? exitBar - start : -1,
    },
  ];

  return <MiniCandles bars={slice} markers={markers} width={88} height={32} />;
}
