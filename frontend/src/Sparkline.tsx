interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  large?: boolean;
}

export function Sparkline({ data, width = 100, height = 32, large = false }: SparklineProps) {
  if (!data || data.length < 2) {
    return <span className="sparkline-empty">—</span>;
  }

  const w = large ? 280 : width;
  const h = large ? 80 : height;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || max * 0.01 || 1;
  const pad = 2;
  const points = data
    .map((v, i) => {
      const x = pad + (i / (data.length - 1)) * (w - pad * 2);
      const y = pad + (1 - (v - min) / range) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const up = data[data.length - 1] >= data[0];
  const stroke = up ? "#3fb950" : "#f85149";
  const fillId = `sp-${Math.random().toString(36).slice(2, 8)}`;
  const areaPoints = `${pad},${h - pad} ${points} ${w - pad},${h - pad}`;

  return (
    <svg
      className={`sparkline ${large ? "sparkline-lg" : ""}`}
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label="price chart"
    >
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill={`url(#${fillId})`} />
      <polyline points={points} fill="none" stroke={stroke} strokeWidth={large ? 2 : 1.5} />
    </svg>
  );
}

export function RsiGauge({ rsi }: { rsi: number }) {
  const pct = Math.max(0, Math.min(100, rsi));
  let color = "#8b949e";
  if (rsi >= 70) color = "#f85149";
  else if (rsi <= 30) color = "#3fb950";
  else if (rsi >= 55) color = "#d29922";

  return (
    <div className="rsi-gauge" title={`RSI ${rsi.toFixed(0)}`}>
      <div className="rsi-bar">
        <div className="rsi-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="rsi-label">{rsi.toFixed(0)}</span>
    </div>
  );
}
