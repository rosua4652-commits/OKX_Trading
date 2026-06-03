import React, { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import { fetchCandles } from "./api";
import { fmtNum, fmtPrice } from "./format";

export type OhlcBar = { o: number; h: number; l: number; c: number };
export type CandlePoint = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

export type ChartLevels = {
  entry?: number;
  stopLoss?: number;
  takeProfit?: number;
  side?: string;
  slPct?: number;
  tpPct?: number;
  currentPrice?: number;
  unrealizedPnl?: number;
  unrealizedPnlPct?: number;
  entryTime?: string;
};

export type MiniCandleMarker = { entry?: number; exit?: number };

export function MiniCandles({
  bars,
  markers,
  width = 100,
  height = 36,
}: {
  bars: OhlcBar[];
  markers?: MiniCandleMarker[];
  width?: number;
  height?: number;
}) {
  if (!bars || bars.length < 2) return <span className="sparkline-empty">—</span>;

  const w = width;
  const h = height;
  const pad = 2;
  const highs = bars.map((b) => b.h);
  const lows = bars.map((b) => b.l);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const range = max - min || max * 0.01 || 1;
  const bw = Math.max(2, (w - pad * 2) / bars.length - 1);

  return (
    <svg width={w} height={h} className="mini-candles" viewBox={`0 0 ${w} ${h}`}>
      {bars.map((b, i) => {
        const x = pad + i * (bw + 1);
        const yHigh = pad + (1 - (b.h - min) / range) * (h - pad * 2);
        const yLow = pad + (1 - (b.l - min) / range) * (h - pad * 2);
        const yOpen = pad + (1 - (b.o - min) / range) * (h - pad * 2);
        const yClose = pad + (1 - (b.c - min) / range) * (h - pad * 2);
        const up = b.c >= b.o;
        const color = up ? "#3fb950" : "#f85149";
        const bodyTop = Math.min(yOpen, yClose);
        const bodyH = Math.max(1, Math.abs(yClose - yOpen));
        return (
          <g key={i}>
            <line x1={x + bw / 2} y1={yHigh} x2={x + bw / 2} y2={yLow} stroke={color} strokeWidth={1} />
            <rect x={x} y={bodyTop} width={bw} height={bodyH} fill={color} />
          </g>
        );
      })}
      {markers?.map((m, mi) => {
        const items: React.ReactElement[] = [];
        if (m.entry != null && m.entry >= 0 && m.entry < bars.length) {
          const x = pad + m.entry * (bw + 1) + bw / 2;
          items.push(
            <line key={`e${mi}`} x1={x} y1={pad} x2={x} y2={h - pad} stroke="#58a6ff" strokeWidth={1} strokeDasharray="2 1" />,
          );
        }
        if (m.exit != null && m.exit >= 0 && m.exit < bars.length) {
          const x = pad + m.exit * (bw + 1) + bw / 2;
          items.push(
            <line key={`x${mi}`} x1={x} y1={pad} x2={x} y2={h - pad} stroke="#d29922" strokeWidth={1} strokeDasharray="2 1" />,
          );
        }
        return items;
      })}
    </svg>
  );
}

function parseEntryTime(iso?: string): UTCTimestamp | null {
  if (!iso) return null;
  const t = Math.floor(new Date(iso).getTime() / 1000);
  return Number.isFinite(t) ? (t as UTCTimestamp) : null;
}

function priceFormatFor(refPrice: number) {
  if (refPrice >= 1000) return { precision: 2, minMove: 0.01 };
  if (refPrice >= 1) return { precision: 4, minMove: 0.0001 };
  if (refPrice >= 0.0001) return { precision: 8, minMove: 0.00000001 };
  return { precision: 12, minMove: 1e-12 };
}

function addLevelLine(
  series: ISeriesApi<"Candlestick">,
  price: number,
  color: string,
  title: string,
  width: 1 | 2 = 1,
  style: 0 | 1 | 2 | 3 = 2,
) {
  if (!Number.isFinite(price) || price <= 0) return;
  series.createPriceLine({
    price,
    color,
    lineWidth: width,
    lineStyle: style,
    axisLabelVisible: true,
    title,
  });
}

export function CandleChart({
  instId,
  strategy,
  height = 320,
  levels,
  pro = false,
}: {
  instId: string;
  strategy: string;
  height?: number;
  levels?: ChartLevels;
  pro?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState("");
  const [meta, setMeta] = useState<{ sl: number; tp: number; method?: string } | null>(null);
  const [levelLabels, setLevelLabels] = useState<{
    entry?: string;
    sl?: string;
    tp?: string;
    current?: string;
  }>({});

  useEffect(() => {
    let cancelled = false;
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#0d1117" },
        textColor: "#8b949e",
      },
      grid: {
        vertLines: { color: "#21262d" },
        horzLines: { color: "#21262d" },
      },
      crosshair: { mode: 1 },
      timeScale: { borderColor: "#30363d", timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#30363d" },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#3fb950",
      downColor: "#f85149",
      borderUpColor: "#3fb950",
      borderDownColor: "#f85149",
      wickUpColor: "#3fb950",
      wickDownColor: "#f85149",
    });

    let volSeries: ISeriesApi<"Histogram"> | null = null;
    if (pro) {
      volSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
      });
      chart.priceScale("vol").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
      });
      series.priceScale().applyOptions({
        scaleMargins: { top: 0.08, bottom: 0.22 },
      });
    }

    const onResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", onResize);

    fetchCandles(instId, strategy, levels?.side === "short" ? "short" : "long")
      .then((data) => {
        if (cancelled) return;
        setMeta({
          sl: data.sl_pct,
          tp: data.tp_pct,
          method: (data as { sl_tp_method?: string }).sl_tp_method,
        });
        const candles = data.candles.map((c) => ({
          time: c.time as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }));
        series.setData(candles);

        const refPrice =
          levels?.entry ?? levels?.currentPrice ?? candles[candles.length - 1]?.close ?? 1;
        const pf = priceFormatFor(refPrice);
        series.applyOptions({
          priceFormat: { type: "price", precision: pf.precision, minMove: pf.minMove },
        });

        if (pro && volSeries) {
          volSeries.setData(
            data.candles.map((c) => ({
              time: c.time as UTCTimestamp,
              value: c.volume ?? 0,
              color: c.close >= c.open ? "#3fb95055" : "#f8514955",
            })),
          );
        }

        chart.timeScale().fitContent();

        const markers: SeriesMarker<UTCTimestamp>[] = [];
        const entryTs = parseEntryTime(levels?.entryTime);
        if (pro && levels?.entry && entryTs) {
          const isLong = levels.side !== "short";
          markers.push({
            time: entryTs,
            position: isLong ? "belowBar" : "aboveBar",
            color: isLong ? "#3fb950" : "#f85149",
            shape: isLong ? "arrowUp" : "arrowDown",
            text: isLong ? "B" : "S",
          });
        }
        if (markers.length) createSeriesMarkers(series, markers);

        const slPct = levels?.slPct ?? data.sl_pct;
        const tpPct = levels?.tpPct ?? data.tp_pct;
        const ref = levels?.entry ?? candles[candles.length - 1]?.close ?? 0;

        let slPrice = levels?.stopLoss;
        let tpPrice = levels?.takeProfit;
        if ((!slPrice || slPrice <= 0) && ref > 0 && slPct != null) {
          slPrice =
            levels?.side === "short"
              ? ref * (1 + slPct / 100)
              : ref * (1 - slPct / 100);
        }
        if ((!tpPrice || tpPrice <= 0) && ref > 0 && tpPct != null) {
          tpPrice =
            levels?.side === "short"
              ? ref * (1 - tpPct / 100)
              : ref * (1 + tpPct / 100);
        }

        const labels: typeof levelLabels = {};
        if (levels?.entry && levels.entry > 0) {
          addLevelLine(series, levels.entry, "#58a6ff", `진입 ${fmtPrice(levels.entry)}`, 2, 0);
          if (pro) addLevelLine(series, levels.entry, "#e6edf399", "Breakeven", 1, 2);
          labels.entry = fmtPrice(levels.entry);
        }
        if (levels?.currentPrice && levels.currentPrice > 0) {
          addLevelLine(series, levels.currentPrice, "#d29922", `현재 ${fmtPrice(levels.currentPrice)}`, 1, 0);
          labels.current = fmtPrice(levels.currentPrice);
        }
        if (slPrice && slPrice > 0) {
          addLevelLine(series, slPrice, "#f85149", `SL -${slPct}% ${fmtPrice(slPrice)}`, 2, 0);
          labels.sl = `${fmtPrice(slPrice)} (-${slPct}%)`;
        }
        if (tpPrice && tpPrice > 0) {
          addLevelLine(series, tpPrice, "#3fb950", `TP +${tpPct}% ${fmtPrice(tpPrice)}`, 2, 0);
          labels.tp = `${fmtPrice(tpPrice)} (+${tpPct}%)`;
        }
        if (!cancelled) setLevelLabels(labels);
      })
      .catch(() => {
        if (!cancelled) setErr("차트 로드 실패");
      });

    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [
    instId,
    strategy,
    height,
    pro,
    levels?.entry,
    levels?.stopLoss,
    levels?.takeProfit,
    levels?.side,
    levels?.slPct,
    levels?.tpPct,
    levels?.currentPrice,
    levels?.entryTime,
  ]);

  const pnl = levels?.unrealizedPnl;
  const pnlPct = levels?.unrealizedPnlPct;

  return (
    <div className="candle-chart-wrap">
      {meta && (
        <p className="chart-sl-tp-hint">
          손절 <strong>{meta.sl}%</strong> · 익절 <strong>{meta.tp}%</strong>
          {meta.method ? <> · <span className="muted">{meta.method}</span></> : null}
          {levels?.entry != null && <> · 진입 ${fmtPrice(levels.entry)}</>}
          {pro && " · 거래량·B/S·손익선"}
        </p>
      )}
      {pro && (levelLabels.entry || levelLabels.sl || levelLabels.tp) && (
        <div className="chart-levels-sidebar">
          {levelLabels.entry && <div>진입 <strong>${levelLabels.entry}</strong></div>}
          {levelLabels.current && <div>현재 <strong>${levelLabels.current}</strong></div>}
          {levelLabels.sl && <div className="sl">손절 <strong>${levelLabels.sl}</strong></div>}
          {levelLabels.tp && <div className="tp">익절 <strong>${levelLabels.tp}</strong></div>}
        </div>
      )}
      {pro && pnl != null && (
        <div className={`chart-pnl-box ${pnl >= 0 ? "positive" : "negative"}`}>
          <span>PnL {pnl >= 0 ? "+" : ""}{fmtNum(pnl)}</span>
          {pnlPct != null && <span> ({fmtNum(pnlPct, 1)}%)</span>}
        </div>
      )}
      {err ? <p className="chart-err">{err}</p> : null}
      <div ref={containerRef} className="candle-chart" style={{ height }} />
    </div>
  );
}
