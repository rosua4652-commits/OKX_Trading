import { useState } from "react";
import { CandleChart, type ChartLevels } from "./CandleChart";
import { TradingViewChart } from "./TradingViewChart";
import { fmtPrice, fmtSlTpCell } from "./format";
import type { Position } from "./types";

export type ChartMode = "tv" | "oat";

export function ChartPanel({
  instId,
  strategy,
  levels,
  position,
  configSl,
  configTp,
  configLeverage = 3,
  defaultMode = "tv",
}: {
  instId: string;
  strategy: string;
  levels?: ChartLevels;
  position?: Position;
  configSl?: number;
  configTp?: number;
  configLeverage?: number;
  defaultMode?: ChartMode;
}) {
  const [mode, setMode] = useState<ChartMode>(defaultMode);

  const posLevels: ChartLevels | undefined = position
    ? {
        entry: position.entry_price,
        stopLoss: position.stop_loss,
        takeProfit: position.take_profit,
        side: position.side,
        slPct: configSl,
        tpPct: configTp,
      }
    : levels;

  const slTp = position
    ? fmtSlTpCell(
        position.entry_price,
        position.stop_loss,
        position.take_profit,
        position.side,
        position.strategy_mode,
      )
    : null;

  return (
    <div className="chart-panel">
      <div className="chart-tabs">
        <button
          type="button"
          className={mode === "tv" ? "active" : ""}
          onClick={() => setMode("tv")}
        >
          TradingView (전체 기능)
        </button>
        <button
          type="button"
          className={mode === "oat" ? "active" : ""}
          onClick={() => setMode("oat")}
        >
          OKX차트 (SL/TP 라인)
        </button>
      </div>

      {position && (
        <div className="position-chart-meta">
          <span className={`badge ${position.side}`}>{position.side.toUpperCase()}</span>
          <span>진입 ${fmtPrice(position.entry_price)}</span>
          {position.instrument_type !== "spot" && (
            <span>
              레버{" "}
              {(position.leverage && position.leverage > 0
                ? position.leverage
                : configLeverage)}
              x
            </span>
          )}
          <span>현재 ${fmtPrice(position.current_price)}</span>
          <span className={position.unrealized_pnl >= 0 ? "positive" : "negative"}>
            PnL {position.unrealized_pnl >= 0 ? "+" : ""}
            {position.unrealized_pnl.toFixed(2)} ({position.unrealized_pnl_pct.toFixed(1)}%)
          </span>
          {slTp && <span>{slTp.text}</span>}
        </div>
      )}

      {mode === "tv" ? (
        <TradingViewChart instId={instId} strategy={strategy} height={position ? 520 : 460} />
      ) : (
        <CandleChart
          instId={instId}
          strategy={strategy}
          height={position ? 360 : 300}
          levels={posLevels}
          pro={!!position}
        />
      )}
    </div>
  );
}
