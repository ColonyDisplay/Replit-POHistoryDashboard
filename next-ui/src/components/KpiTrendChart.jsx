"use client";

import { formatKpiValue } from "./kpiFormat";

function numericPoints(points) {
  return (points || []).map((point) => ({ ...point, n: Number(point.value) }))
    .filter((point) => Number.isFinite(point.n));
}

function EmptyTrend() {
  return <div className="kpi-chart-empty">No published trend data</div>;
}

export function DailyTrend({ points, unit, label }) {
  const values = numericPoints(points);
  if (!values.length) return <EmptyTrend />;
  const min = Math.min(...values.map((point) => point.n));
  const max = Math.max(...values.map((point) => point.n));
  const range = max - min || 1;
  const path = values.map((point, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100;
    const y = 31 - ((point.n - min) / range) * 25;
    return `${x},${y}`;
  }).join(" ");
  const last = values[values.length - 1];

  return (
    <div className="kpi-chart">
      <div className="kpi-chart-heading">
        <span>Daily · last 30</span>
        <strong>{formatKpiValue(last.n, unit, label)}</strong>
      </div>
      <svg viewBox="0 0 100 36" preserveAspectRatio="none" aria-label="30 day trend">
        <line x1="0" y1="31" x2="100" y2="31" className="kpi-chart-axis" />
        <polyline points={path} className="kpi-chart-line" />
      </svg>
      <div className="kpi-chart-range">
        <span>{values[0]?.date}</span><span>{last?.date}</span>
      </div>
    </div>
  );
}

export function MonthlyTrend({ points, unit, label }) {
  const values = numericPoints(points);
  if (!values.length) return <EmptyTrend />;
  const max = Math.max(...values.map((point) => Math.abs(point.n)), 1);

  return (
    <div className="kpi-chart">
      <div className="kpi-chart-heading">
        <span>Monthly · trailing 12</span>
        <strong>{formatKpiValue(values[values.length - 1].n, unit, label)}</strong>
      </div>
      <div className="kpi-month-bars" aria-label="12 month trend">
        {values.map((point) => (
          <div className="kpi-month-column" key={`${point.year}-${point.month}`}>
            <div
              className="kpi-month-bar"
              style={{ height: `${Math.max(3, (Math.abs(point.n) / max) * 100)}%` }}
              title={`${point.label}: ${formatKpiValue(point.n, unit, label)}`}
            />
            <span>{point.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}