"use client";

import { useEffect, useState } from "react";
import { getDataLakeReport } from "./api";

const TABS = [
  { id: "shipping", label: "Shipping logs" },
  { id: "catalog", label: "Catalog" },
  { id: "tables", label: "Tables" },
  { id: "freshness", label: "Freshness" },
  { id: "periods", label: "Period comparisons" },
];

function stateCopy(envelope, error) {
  const payload = error?.payload;
  const state = payload?.state || envelope?.state;
  const message = payload?.message || envelope?.message;
  if (error) {
    if (state === "not_configured") return { className: "notice", title: "Configuration required", body: message || "This report is not configured for this environment." };
    if (state === "upstream_error") return { className: "failure", title: "Upstream service failed", body: message || "The source system did not complete the request.", retry: true };
    if (state === "unavailable") return { className: "notice", title: "Report unavailable", body: message || "This report is not available right now.", retry: true };
    if (state === "invalid_request") return { className: "failure", title: "Invalid request", body: message || "Review the request and try again." };
    if (state === "empty") return { className: "empty", title: "No data is available", body: message || "This report completed but did not return records." };
    return { className: "failure", title: "Request failed", body: message || error.message || "The report could not be reached.", retry: true };
  }
  if (state === "ok") return null;
  if (state === "empty") return { className: "empty", title: "No data is available", body: message || "This report completed but did not return records." };
  if (state === "not_configured") return { className: "notice", title: "Configuration required", body: message || "This report is not configured for this environment." };
  if (state === "upstream_error") return { className: "failure", title: "Upstream service failed", body: message || "The source system did not complete the request.", retry: true };
  if (state === "unavailable") return { className: "notice", title: "Report unavailable", body: message || "This report is not available right now.", retry: true };
  if (state === "invalid_request") return { className: "failure", title: "Invalid request", body: message || "Review the request and try again." };
  return { className: "notice", title: "Report status unavailable", body: message || "The report returned an unrecognized status.", retry: true };
}

function useLakeReport(report) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryIndex, setRetryIndex] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getDataLakeReport(report)
      .then((value) => { if (alive) setResult(value); })
      .catch((reason) => { if (alive) setError(reason); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [report, retryIndex]);

  return {
    result,
    loading,
    state: stateCopy(result, error),
    retry: () => setRetryIndex((value) => value + 1),
  };
}

function LoadingReport({ label }) {
  return (
    <div className="lake-loading" aria-label={`Loading ${label}`}>
      <span /><span /><span />
    </div>
  );
}

function ReportState({ state, onRetry, compact = false }) {
  if (!state) return null;
  return (
    <div className={`lake-state ${state.className} ${compact ? "compact" : ""}`}>
      <span className="lake-state-mark" aria-hidden="true" />
      <div>
        <strong>{state.title}</strong>
        <p>{state.body}</p>
        {state.retry && (
          <button className="lake-button secondary" type="button" onClick={onRetry}>
            Retry report
          </button>
        )}
      </div>
    </div>
  );
}

function formatTimestamp(value) {
  if (!value) return "Not reported";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(parsed);
}

function formatQuantity(value, signed = false) {
  if (value === null || value === undefined || (typeof value === "string" && value.trim() === "")) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "—";
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
  }).format(Math.abs(number));
  if (!signed) return number < 0 ? `-${formatted}` : formatted;
  if (number > 0) return `+${formatted}`;
  if (number < 0) return `-${formatted}`;
  return formatted;
}

function SurfaceHeader({ eyebrow, title, titleId, description, meta }) {
  return (
    <div className="lake-surface-head">
      <div>
        <span className="lake-eyebrow">{eyebrow}</span>
        <h3 id={titleId}>{title}</h3>
        <p>{description}</p>
      </div>
      {meta && <span className="lake-meta-pill">{meta}</span>}
    </div>
  );
}

function ShippingLogs() {
  const report = useLakeReport("shipping_logs");
  const data = report.result?.data;
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  return (
    <section className="lake-surface" aria-labelledby="shipping-title">
      <SurfaceHeader
        eyebrow="Default report"
        title="Shipping logs"
        titleId="shipping-title"
        description="Latest shipment lines returned by the approved shipping_logs query."
        meta={data ? `${data.returned ?? rows.length} rows` : null}
      />
      {report.loading ? <LoadingReport label="shipping logs" /> :
        report.state ? <ReportState state={report.state} onRetry={report.retry} /> :
          rows.length === 0 ? <ReportState state={{ className: "empty", title: "No shipping rows", body: "The report completed successfully but returned no shipment lines." }} /> :
            <>
              <div className="lake-report-bar">
                <span><b>Query</b> {data.query || "shipping_logs"}</span>
                <span><b>Checked</b> {formatTimestamp(data.checked_at)}</span>
              </div>
              <div className="lake-table-scroll">
                <table className="lake-table lake-shipping-table">
                  <caption>Shipping logs returned by DataLake</caption>
                  <thead>
                    <tr>
                      <th scope="col">Pack #</th>
                      <th scope="col">Ship date</th>
                      <th scope="col">Customer</th>
                      <th scope="col">Part</th>
                      <th scope="col">Order</th>
                      <th scope="col">Pack line</th>
                      <th scope="col" className="number">Ship qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={`${row.Company}-${row.PackNum}-${row.PackLine}-${index}`}>
                        <td><span className="lake-primary-cell">{row.PackNum ?? "—"}</span><small>{row.Company || "—"}</small></td>
                        <td>{row.ShipDate || "—"}</td>
                        <td><span className="lake-primary-cell">{row.CustID || "—"}</span><small>{row.CustNum ?? "—"}</small></td>
                        <td>{row.PartNum || "—"}</td>
                        <td><span className="lake-primary-cell">{row.OrderNum ?? "—"}</span><small>Line {row.OrderLine ?? "—"}</small></td>
                        <td>{row.PackLine ?? "—"}</td>
                        <td className="number lake-quantity">{formatQuantity(row.OurInventoryShipQty)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>}
    </section>
  );
}

function SummaryCards({ data }) {
  const items = [
    ["Total tables", data?.count],
    ["SCD2", data?.by_class?.scd2],
    ["Append", data?.by_class?.append],
    ["Snapshot", data?.by_class?.snapshot],
  ];
  return (
    <div className="lake-summary-grid">
      {items.map(([label, value]) => (
        <div className="lake-summary-card" key={label}>
          <span>{label}</span>
          <strong>{value ?? "—"}</strong>
        </div>
      ))}
    </div>
  );
}

function TableDirectory({ rows }) {
  return (
    <div className="lake-table-scroll lake-directory-scroll">
      <table className="lake-table">
        <caption>DataLake table directory</caption>
        <thead><tr><th scope="col">Table</th><th scope="col">Class</th><th scope="col">Keys</th><th scope="col">Watermark</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.table}>
              <td className="lake-primary-cell">{row.table}</td>
              <td><span className={`lake-class-tag ${row.class || ""}`}>{row.class || "—"}</span></td>
              <td>{Array.isArray(row.keys) && row.keys.length ? row.keys.join(", ") : "—"}</td>
              <td>{row.watermark || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Catalog() {
  const catalog = useLakeReport("catalog");
  const queries = useLakeReport("queries");
  const data = catalog.result?.data;
  const queryData = queries.result?.data;
  const rows = Array.isArray(data?.tables) ? data.tables : [];
  const queryRows = Array.isArray(queryData?.queries) ? queryData.queries : [];
  return (
    <div className="lake-stack">
      <section className="lake-surface" aria-labelledby="catalog-title">
        <SurfaceHeader eyebrow="Source registry" title="Catalog" titleId="catalog-title" description="Approved table classes currently exposed by lake-api." meta={data ? `${data.count ?? rows.length} tables` : null} />
        {catalog.loading ? <LoadingReport label="catalog" /> :
          catalog.state ? <ReportState state={catalog.state} onRetry={catalog.retry} /> :
            <div className="lake-section-body"><SummaryCards data={data} /></div>}
      </section>
      <section className="lake-surface" aria-labelledby="queries-title">
        <SurfaceHeader eyebrow="Report registry" title="Available queries" titleId="queries-title" description="Read-only operational queries registered by the upstream service." meta={queryData ? `${queryData.count ?? queryRows.length} queries` : null} />
        {queries.loading ? <LoadingReport label="query registry" /> :
          queries.state ? <ReportState state={queries.state} onRetry={queries.retry} /> :
            <div className="lake-query-grid">
              {queryRows.map((query) => (
                <article className="lake-query-card" key={query.name}>
                  <div><span className="lake-status-dot" />{query.status || "registered"}</div>
                  <h4>{query.name}</h4>
                  <p>{query.summary || "Operational DataLake query."}</p>
                  <small>{Array.isArray(query.tables) ? query.tables.join(" · ") : "No tables listed"}</small>
                </article>
              ))}
            </div>}
      </section>
    </div>
  );
}

function Tables() {
  const report = useLakeReport("tables");
  const data = report.result?.data;
  const rows = Array.isArray(data?.tables) ? data.tables : [];
  return (
    <section className="lake-surface" aria-labelledby="tables-title">
      <SurfaceHeader eyebrow="Table registry" title="Tables" titleId="tables-title" description="Current table directory, classification, business keys, and watermarks." meta={data ? `${data.count ?? rows.length} tables` : null} />
      {report.loading ? <LoadingReport label="tables" /> :
        report.state ? <ReportState state={report.state} onRetry={report.retry} /> :
          rows.length === 0 ? <ReportState state={{ className: "empty", title: "No tables returned", body: "The table registry is currently empty." }} /> :
            <><div className="lake-section-body"><SummaryCards data={data} /></div><TableDirectory rows={rows} /></>}
    </section>
  );
}

function Freshness() {
  const report = useLakeReport("freshness");
  const data = report.result?.data;
  const items = [
    ["Latest snapshot", data?.latest_snapshot_date],
    ["Latest load", data?.latest_load_date],
    ["Tables checked", data?.tables_checked],
    ["Checked at", formatTimestamp(data?.checked_at)],
  ];
  return (
    <section className="lake-surface" aria-labelledby="freshness-title">
      <SurfaceHeader eyebrow="Data currency" title="Freshness" titleId="freshness-title" description="Latest source dates reported by lake-api. No dates are estimated by the portal." meta={data?.status || null} />
      {report.loading ? <LoadingReport label="freshness" /> :
        report.state ? <ReportState state={report.state} onRetry={report.retry} /> :
          <div className="lake-freshness-grid">
            {items.map(([label, value]) => <div className="lake-freshness-card" key={label}><span>{label}</span><strong>{value ?? "—"}</strong></div>)}
          </div>}
    </section>
  );
}

function ComparisonCard({ reportName, title, description }) {
  const report = useLakeReport(reportName);
  const data = report.result?.data;
  const metrics = Array.isArray(data?.metrics) ? data.metrics[0] : null;
  const rawDelta = metrics?.qty_delta;
  const delta = rawDelta === null || rawDelta === undefined || (typeof rawDelta === "string" && rawDelta.trim() === "") ? Number.NaN : Number(rawDelta);
  return (
    <section className="lake-surface lake-comparison" aria-labelledby={`${reportName}-title`}>
      <SurfaceHeader eyebrow={data?.period || reportName} title={title} titleId={`${reportName}-title`} description={description} meta={data?.status || null} />
      {report.loading ? <LoadingReport label={title} /> :
        report.state ? <ReportState state={report.state} onRetry={report.retry} compact /> :
          !metrics ? <ReportState state={{ className: "empty", title: "No comparison returned", body: "The report completed but did not return period metrics." }} compact /> :
            <div className="lake-comparison-body">
              <div className="lake-period">
                <span>Current period</span>
                <strong>{formatQuantity(metrics.qty_this)}</strong>
                <small>{metrics.this_from} — {metrics.this_to}</small>
              </div>
              <div className="lake-period">
                <span>Previous period</span>
                <strong>{formatQuantity(metrics.qty_prev)}</strong>
                <small>{metrics.prev_from} — {metrics.prev_to}</small>
              </div>
              <div className={`lake-period delta ${Number.isFinite(delta) ? delta < 0 ? "negative" : "positive" : ""}`}>
                <span>Net change</span>
                <strong>{formatQuantity(metrics.qty_delta, true)}</strong>
                <small>Inventory ship quantity</small>
              </div>
            </div>}
    </section>
  );
}

function PeriodComparisons() {
  return (
    <div className="lake-comparison-grid">
      <ComparisonCard reportName="wow" title="Week over week" description="Current shipping quantity compared with the previous week." />
      <ComparisonCard reportName="mom" title="Month over month" description="Current shipping quantity compared with the previous month." />
    </div>
  );
}

function PreviewUnavailable() {
  return (
    <section className="lake-surface">
      <SurfaceHeader eyebrow="Preview safeguard" title="Live DataLake reports are paused" titleId="preview-title" description="Sample Preview does not request protected lake data and does not substitute fictional rows." />
      <ReportState state={{ className: "notice", title: "Enable live read-only Preview", body: "Open this section with live Preview enabled or sign in as an authorized production admin to load operational reports." }} />
    </section>
  );
}

export default function DataLakeDashboard({ onReturnHome, previewMode = false }) {
  const [activeTab, setActiveTab] = useState("shipping");
  const moveTabFocus = (event, tabId) => {
    const currentIndex = TABS.findIndex((tab) => tab.id === tabId);
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % TABS.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = TABS.length - 1;
    else return;
    event.preventDefault();
    const nextId = TABS[nextIndex].id;
    setActiveTab(nextId);
    requestAnimationFrame(() => document.getElementById(`lake-tab-${nextId}`)?.focus());
  };
  const renderActiveTab = () => {
    if (previewMode) return <PreviewUnavailable />;
    if (activeTab === "catalog") return <Catalog />;
    if (activeTab === "tables") return <Tables />;
    if (activeTab === "freshness") return <Freshness />;
    if (activeTab === "periods") return <PeriodComparisons />;
    return <ShippingLogs />;
  };

  return (
    <main className="datalake-page">
      <div className="datalake-intro">
        <div>
          <div className="datalake-kicker">COLONY DISPLAY · RESTRICTED REPORTING</div>
          <h2>DataLake</h2>
          <p>{previewMode ? "Protected reporting is unavailable in sample Preview; no fictional DataLake rows are substituted." : "Live operational reporting for authorized administrators. Values are displayed from the approved lake-api response without estimation."}</p>
        </div>
        <div className="lake-privilege"><span />{previewMode ? "Preview · No live data" : "Admin only · Live"}</div>
      </div>
      <div className="lake-tabs" role="tablist" aria-label="DataLake reports">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            id={`lake-tab-${tab.id}`}
            className={`lake-tab ${activeTab === tab.id ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls="lake-active-panel"
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(event) => moveTabFocus(event, tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div id="lake-active-panel" className="lake-active-panel" role="tabpanel" aria-labelledby={`lake-tab-${activeTab}`}>
        {renderActiveTab()}
      </div>
      <button className="datalake-home-link" type="button" onClick={onReturnHome}>Return to dashboard home</button>
    </main>
  );
}