"use client";

import { useEffect, useMemo, useState } from "react";
import { getKpiDetail } from "./api";
import { DailyTrend, MonthlyTrend } from "./KpiTrendChart";
import { formatKpiValue } from "./kpiFormat";

function displayCell(value) {
  if (value == null || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function KpiDetailPanel({ metric, trend, asOf, onClose }) {
  const [grain, setGrain] = useState("date");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const period = grain === "date" ? asOf : asOf?.slice(0, 7);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setDetail(null);
    getKpiDetail(metric.id, { [grain]: period })
      .then((payload) => active && setDetail(payload))
      .catch((requestError) => {
        if (!active) return;
        setError(requestError.status === 404
          ? "Detail for this period has not been published yet."
          : requestError.message);
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [metric.id, grain, period]);

  const columns = useMemo(() => {
    const rows = detail?.rows || [];
    const keys = [];
    rows.slice(0, 50).forEach((row) => {
      Object.keys(row || {}).forEach((key) => {
        if (!keys.includes(key)) keys.push(key);
      });
    });
    return keys;
  }, [detail]);

  const visibleRows = (detail?.rows || []).slice(0, 500);

  return (
    <div className="kpi-detail-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className="kpi-detail-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${metric.label} published detail`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="kpi-detail-header">
          <div>
            <small>{metric.id} · Published detail</small>
            <h2>{metric.label}</h2>
            <p>{period}</p>
          </div>
          <button type="button" className="kpi-close" onClick={onClose} aria-label="Close detail">×</button>
        </div>

        <div className="kpi-detail-grain">
          <button type="button" className={grain === "date" ? "active" : ""} onClick={() => setGrain("date")}>
            Daily detail
          </button>
          <button type="button" className={grain === "month" ? "active" : ""} onClick={() => setGrain("month")}>
            Monthly detail
          </button>
        </div>

        <div className="kpi-detail-charts">
          <DailyTrend points={trend?.dailyLast30} unit={metric.unit} label={metric.label} />
          <MonthlyTrend points={trend?.monthlyTrailing12} unit={metric.unit} label={metric.label} />
        </div>

        {loading ? (
          <div className="kpi-inline-state">Loading published detail…</div>
        ) : error ? (
          <div className="kpi-inline-state kpi-inline-error">{error}</div>
        ) : detail ? (
          <>
            <div className="kpi-detail-totals">
              <span><small>Rows</small>{detail.rowCount ?? visibleRows.length}</span>
              {Object.entries(detail.totals || {}).map(([key, value]) => (
                <span key={key}>
                  <small>{key}</small>
                  {formatKpiValue(value, metric.unit, key)}
                </span>
              ))}
            </div>
            {visibleRows.length ? (
              <div className="kpi-detail-table-wrap">
                <table className="kpi-detail-table">
                  <thead>
                    <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {columns.map((column) => <td key={column}>{displayCell(row[column])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="kpi-inline-state">This published result has no detail rows.</div>
            )}
            {(detail.rows || []).length > visibleRows.length && (
              <p className="kpi-row-limit">Showing the first 500 published rows.</p>
            )}
          </>
        ) : null}
      </aside>
    </div>
  );
}