import { fmtNum } from "./format";
import {
  computeAllocation,
  pieArcs,
  type AllocationSlice,
} from "./portfolioAllocation";
import type { Portfolio } from "./types";

function SliceLegend({ slice }: { slice: AllocationSlice }) {
  return (
    <div className="alloc-legend-row">
      <span className="alloc-dot" style={{ background: slice.color }} />
      <span className="alloc-name" title={slice.instId}>
        {slice.label}
        {slice.side ? (
          <span className={`badge ${slice.side}`} style={{ marginLeft: 6, fontSize: "0.65rem" }}>
            {slice.side.toUpperCase()}
          </span>
        ) : null}
      </span>
      <span className="alloc-amt">${fmtNum(slice.margin, 0)}</span>
      <span className="alloc-pct">{fmtNum(slice.pct, 1)}%</span>
    </div>
  );
}

export function AssetAllocationPanel({
  portfolio,
  defaultLeverage,
  tradeMode,
  moneyTag = "USD",
}: {
  portfolio: Portfolio;
  defaultLeverage: number;
  tradeMode: string;
  moneyTag?: string;
}) {
  const data = computeAllocation(portfolio, defaultLeverage);
  const { slices, deployed, available, equity, unrealizedPnl } = data;
  const arcs = pieArcs(slices, 90, 90, 82, 48);
  const positionSlices = slices.filter((s) => s.key !== "available");
  const hasPositions = positionSlices.length > 0;

  if (!hasPositions && available <= 0) {
    return null;
  }

  return (
    <div className="section portfolio-alloc">
      <h2>
        자산 배분 ({moneyTag})
      </h2>
      <div className="alloc-layout">
        <div className="alloc-chart-wrap">
          <svg viewBox="0 0 180 180" className="alloc-pie" role="img" aria-label="자산 배분">
            {arcs.length === 0 ? (
              <circle cx="90" cy="90" r="82" fill="#21262d" />
            ) : (
              arcs.map((a) => (
                <path key={a.key} d={a.d} fill={a.color} stroke="#0d1117" strokeWidth="1.5">
                  <title>{`${a.key} ${fmtNum(a.pct, 1)}%`}</title>
                </path>
              ))
            )}
            <circle cx="90" cy="90" r="46" fill="#0d1117" />
            <text x="90" y="82" textAnchor="middle" fill="#8b949e" fontSize="9">
              총 자산
            </text>
            <text x="90" y="98" textAnchor="middle" fill="#e6edf3" fontSize="11" fontWeight="600">
              ${fmtNum(equity, 0)}
            </text>
            {Math.abs(unrealizedPnl) >= 0.01 && (
              <text
                x="90"
                y="112"
                textAnchor="middle"
                fill={unrealizedPnl >= 0 ? "#3fb950" : "#f85149"}
                fontSize="8"
              >
                UPNL {unrealizedPnl >= 0 ? "+" : ""}
                {fmtNum(unrealizedPnl, 0)}
              </text>
            )}
          </svg>
          <div className="alloc-summary-mini">
            <span>
              투입 증거금 <strong>${fmtNum(deployed, 0)}</strong>
            </span>
            <span>
              가용 <strong>${fmtNum(available, 0)}</strong>
            </span>
          </div>
        </div>

        <div className="alloc-detail">
          <div className="alloc-legend">
            {positionSlices.map((s) => (
              <SliceLegend key={s.key} slice={s} />
            ))}
            {slices
              .filter((s) => s.key === "available")
              .map((s) => (
                <SliceLegend key={s.key} slice={s} />
              ))}
          </div>

          {hasPositions && (
            <table className="alloc-table">
              <thead>
                <tr>
                  <th>종목</th>
                  <th>증거금</th>
                  <th>명목</th>
                  <th>비중</th>
                  <th>UPNL</th>
                </tr>
              </thead>
              <tbody>
                {positionSlices.map((s) => (
                  <tr key={s.key}>
                    <td>{s.label}</td>
                    <td>${fmtNum(s.margin, 0)}</td>
                    <td className="muted">${fmtNum(s.notional, 0)}</td>
                    <td>{fmtNum(s.pct, 1)}%</td>
                    <td className={(s.unrealizedPnl ?? 0) >= 0 ? "positive" : "negative"}>
                      {(s.unrealizedPnl ?? 0) >= 0 ? "+" : ""}
                      {fmtNum(s.unrealizedPnl ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="alloc-hint">
            비중 = 증거금 ÷ (투입 증거금 + 가용). 선물은 레버리지 적용 후 실제 묶인 {moneyTag} 기준입니다.
          </p>
        </div>
      </div>
    </div>
  );
}
