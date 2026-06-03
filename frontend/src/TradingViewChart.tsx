import { useEffect, useMemo, useState } from "react";
import {
  strategyToTvInterval,
  tradingViewSymbolOptions,
  type TvSymbolOption,
} from "./chartSymbols";

function buildEmbedUrl(symbol: string, strategy: string): string {
  const interval = strategyToTvInterval(strategy);
  const params = new URLSearchParams({
    symbol,
    interval,
    theme: "dark",
    style: "1",
    locale: "kr",
    timezone: "Asia/Seoul",
    hide_side_toolbar: "0",
    allow_symbol_change: "1",
    saveimage: "0",
    studies: "Volume@tv-basicstudies",
  });
  return `https://s.tradingview.com/widgetembed/?${params.toString()}`;
}

export function TradingViewChart({
  instId,
  strategy,
  height = 420,
}: {
  instId: string;
  strategy: string;
  height?: number;
}) {
  const options = useMemo(() => tradingViewSymbolOptions(instId), [instId]);
  const [active, setActive] = useState<TvSymbolOption>(() => options[0]);

  useEffect(() => {
    setActive(options[0]);
  }, [instId, options]);

  const embedUrl = useMemo(
    () => buildEmbedUrl(active.symbol, strategy),
    [active.symbol, strategy],
  );

  const isAltFallback =
    instId.endsWith("-SWAP") &&
    active.id === "binance-swap" &&
    !options.some((o) => o.id === "okx-swap");

  return (
    <div className="tv-chart-wrap" style={{ minHeight: height }}>
      <p className="chart-sl-tp-hint">
        TradingView · {instId}
        {isAltFallback && (
          <span className="tv-fallback-note">
            {" "}
            (OKX {instId.replace("-USDT-SWAP", "")} 무기한 미등록 → Binance PERP 참고 차트)
          </span>
        )}
      </p>
      <div className="tv-symbol-picks">
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            className={active.id === o.id ? "active" : ""}
            onClick={() => setActive(o)}
            title={o.symbol}
          >
            {o.label}
          </button>
        ))}
      </div>
      <iframe
        key={`${active.symbol}-${strategy}`}
        title={`TradingView ${active.symbol}`}
        src={embedUrl}
        className="tv-embed-frame"
        style={{ width: "100%", height: height - 56, border: "none", borderRadius: 8 }}
        allowFullScreen
      />
    </div>
  );
}
