"use client";

import { formatKpiValue } from "./kpiFormat";

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export default function KpiMetricCard({ metric, trend, selected, onSelect }) {
  const interactive = typeof onSelect === "function";
  const Card = interactive ? "button" : "article";
  const points = (trend?.dailyLast30 || [])
    .map((point) => finiteNumber(point.value))
    .filter((value) => value != null);
  const average30d = points.length ? points.reduce((total, point) => total + point, 0) / points.length : null;
  const daily = finiteNumber(metric.daily);
  const avg7 = finiteNumber(metric.avg7);
  const comparison = daily != null && avg7 != null && avg7 !== 0
    ? ((daily - avg7) / Math.abs(avg7)) * 100
    : null;
  const spark = points.length > 1 ? points.map((value, index) => {
    const min = Math.min(...points); const range = Math.max(...points) - min || 1;
    return `${(index / (points.length - 1)) * 100},${26 - ((value - min) / range) * 22}`;
  }).join(" ") : "";
  return (
    <Card
      {...(interactive ? {
        type: "button",
        onClick: () => onSelect(metric),
        "aria-pressed": selected,
      } : {})}
      className={`kpi-metric-card ${selected ? "selected" : ""} ${interactive ? "" : "noninteractive"}`}
    >
      <div className="kpi-metric-title">
        <span>{metric.label}</span>
        <small>{metric.unit || metric.id}</small>
      </div>
      <div className="kpi-primary-value">
        {formatKpiValue(metric.daily, metric.unit, metric.label)}
        {metric.unit && !/\$|usd/i.test(`${metric.unit} ${metric.label}`) && (
          <small>{metric.unit}</small>
        )}
      </div>
      {comparison != null && <div className={`kpi-delta ${comparison < 0 ? "negative" : "positive"}`}>{comparison >= 0 ? "+" : ""}{comparison.toFixed(1)}% vs 7-day avg</div>}
      <div className="kpi-metric-stats">
        <span><small>7-day avg</small>{formatKpiValue(metric.avg7, metric.unit, metric.label)}</span>
        <span><small>30-day avg</small>{formatKpiValue(average30d, metric.unit, metric.label)}</span>
      </div>
      {spark && <svg className="kpi-card-spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-label={`${metric.label} 30-day trend`}><polyline points={spark} /></svg>}
      {metric.mtd != null && <p><strong>MTD</strong> {formatKpiValue(metric.mtd, metric.unit, metric.label)}</p>}
      {metric.target != null && <p><strong>Target</strong> {formatKpiValue(metric.target, metric.unit, metric.label)}</p>}
      {metric.note && <p>{metric.note}</p>}
      <div className="kpi-card-action">View published detail →</div>
    </Card>
  );
}