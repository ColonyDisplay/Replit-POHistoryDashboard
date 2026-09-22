"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getKpiHealth, getKpis, getKpiTrends } from "./api";
import KpiDetailPanel from "./KpiDetailPanel";
import KpiMetricCard from "./KpiMetricCard";
import { formatBusinessDate } from "./kpiFormat";

const SUMMARY_BLOCKS = [
  { id: "shipping", title: "Shipping", metrics: ["SH-01", "SH-02", "SH-03", "SH-AVG-UNIT"] },
  { id: "receiving", title: "Receiving", metrics: ["RC-01", "RC-02", "RC-04", "RC-05"] },
  { id: "inventory", title: "Inventory", metrics: ["IV-02", "IV-05-USD", "IV-04-USD", "IV-03-USD"] },
  { id: "fabrication", title: "Fabrication", metrics: ["FAB-01", "FAB-02", "FAB-04", "FAB-05"] },
  { id: "assembly", title: "Assembly", metrics: ["ASM-01", "ASM-02", "KIT-01", "KIT-02"] },
];

function metricMap(sections) {
  return new Map((sections || []).flatMap((section) => section.metrics || []).map((metric) => [metric.id, metric]));
}

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function ratio(numerator, denominator) {
  const left = finiteNumber(numerator);
  const right = finiteNumber(denominator);
  return left != null && right != null && right !== 0 ? left / right : null;
}

function pointKey(point, index) {
  return point?.date || point?.month || point?.period || index;
}

function ratioSeries(numerator = [], denominator = []) {
  const denominators = new Map(denominator.map((point, index) => [pointKey(point, index), point]));
  return numerator.flatMap((point, index) => {
    const value = ratio(point?.value, denominators.get(pointKey(point, index))?.value);
    return value == null ? [] : [{ ...point, value }];
  });
}

function buildAveragePerUnit(byId, trends) {
  const units = byId.get("SH-01");
  const dollars = byId.get("SH-02");
  if (!units || !dollars) return null;

  return {
    metric: {
      id: "SH-AVG-UNIT",
      label: "Avg $ / unit",
      unit: "USD/EA",
      daily: ratio(dollars.daily, units.daily),
      mtd: ratio(dollars.mtd, units.mtd),
      avg7: ratio(dollars.avg7, units.avg7),
      derived: true,
    },
    trend: {
      dailyLast30: ratioSeries(
        trends?.metrics?.["SH-02"]?.dailyLast30,
        trends?.metrics?.["SH-01"]?.dailyLast30,
      ),
      monthlyTrailing12: ratioSeries(
        trends?.metrics?.["SH-02"]?.monthlyTrailing12,
        trends?.metrics?.["SH-01"]?.monthlyTrailing12,
      ),
    },
  };
}

function SummaryBlocks({ sections, trends, selectedMetric, onSelect }) {
  const byId = metricMap(sections);
  const averagePerUnit = buildAveragePerUnit(byId, trends);
  if (averagePerUnit) byId.set(averagePerUnit.metric.id, averagePerUnit.metric);

  return (
    <div className="kpi-summary-groups" aria-label="Daily summary">
      {SUMMARY_BLOCKS.map((block) => {
        const metrics = block.metrics.map((id) => byId.get(id)).filter(Boolean);
        if (!metrics.length) return null;
        return (
          <section className="kpi-group kpi-summary-group" key={block.id} aria-labelledby={`summary-${block.id}`}>
            <div className="kpi-group-heading">
              <h3 id={`summary-${block.id}`}>{block.title}</h3>
              <small>{metrics.length} summary</small>
            </div>
            <div className="kpi-metric-grid">
              {metrics.map((metric) => (
                <KpiMetricCard
                  key={metric.id}
                  metric={metric}
                  trend={metric.derived ? averagePerUnit?.trend : trends?.metrics?.[metric.id]}
                  selected={!metric.derived && selectedMetric?.id === metric.id}
                  onSelect={metric.derived ? undefined : onSelect}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function SectionMetrics({ section, trends, selectedMetric, onSelect }) {
  const subsections = [];
  for (const metric of section?.metrics || []) {
    const title = metric.subsection || "";
    let group = subsections.find((item) => item.title === title);
    if (!group) {
      group = { title, metrics: [] };
      subsections.push(group);
    }
    group.metrics.push(metric);
  }

  if (subsections.length === 1 && !subsections[0].title) {
    return (
      <div className="kpi-metric-grid">
        {subsections[0].metrics.map((metric) => (
          <KpiMetricCard key={metric.id} metric={metric} trend={trends?.metrics?.[metric.id]} selected={selectedMetric?.id === metric.id} onSelect={onSelect} />
        ))}
      </div>
    );
  }

  return subsections.map((group, index) => (
    <section className="kpi-group" key={group.title || "overview"} aria-labelledby={`subsection-${section?.id}-${index}`}>
      <div className="kpi-group-heading">
        <h3 id={`subsection-${section?.id}-${index}`}>{group.title || "Overview"}</h3>
        <small>{group.metrics.length} metrics</small>
      </div>
      <div className="kpi-metric-grid">
        {group.metrics.map((metric) => (
          <KpiMetricCard key={metric.id} metric={metric} trend={trends?.metrics?.[metric.id]} selected={selectedMetric?.id === metric.id} onSelect={onSelect} />
        ))}
      </div>
    </section>
  ));
}

function formatTimestamp(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(parsed);
}

function Freshness({ health, message, previewMode, latestMode, selectedDate, asOf }) {
  const state = health?.state || "error";
  const publishedDate = health?.latestSuccessfulPublish || asOf;
  const lastSuccess = health?.lastSuccessfulPublishAt
    || health?.latestSuccessfulPublishAt
    || health?.lastSuccessAt
    || health?.lastSuccessTimestamp;
  const heading = previewMode
    ? "Unsigned sample preview"
    : latestMode
      ? state === "ok" ? "Latest published Neon results" : "Latest Neon publish needs attention"
      : "Historical Neon results";

  return (
    <div className={`kpi-freshness ${previewMode ? "preview" : state}`} role={state === "ok" || previewMode ? undefined : "status"}>
      <span className="kpi-freshness-dot" />
      <div>
        <strong>{heading}</strong>
        <span>
          {message || (previewMode
            ? `Sample source · selected date ${formatBusinessDate(asOf || selectedDate)} · not connected to Neon.`
            : [
              "Source Neon",
              `selected date ${formatBusinessDate(selectedDate || asOf)}`,
              publishedDate && `latest published ${formatBusinessDate(publishedDate)}`,
              `last success ${lastSuccess ? formatTimestamp(lastSuccess) : "unavailable"}`,
            ].filter(Boolean).join(" · "))}
        </span>
      </div>
    </div>
  );
}

export default function OpsKpiDashboard({ previewMode = false }) {
  const [selectedDate, setSelectedDate] = useState("");
  const [latestMode, setLatestMode] = useState(true);
  const [summary, setSummary] = useState(null);
  const [trends, setTrends] = useState(null);
  const [health, setHealth] = useState(null);
  const [activeSection, setActiveSection] = useState("daily-summary");
  const [selectedMetric, setSelectedMetric] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const requestSequence = useRef(0);

  const load = useCallback(async ({ date, latest }) => {
    const requestId = ++requestSequence.current;
    setLoading(true);
    setError(null);
    setNotice("");
    setSelectedMetric(null);

    const healthPromise = getKpiHealth()
      .then((payload) => {
        if (requestId === requestSequence.current) setHealth(payload);
      })
      .catch(() => {
        if (requestId === requestSequence.current) setHealth({ state: "error" });
      });

    try {
      const loadedSummary = await getKpis(latest ? undefined : date);
      // Pin trends to the returned summary date so the chart can never describe another publication.
      const loadedTrends = await getKpiTrends(loadedSummary?.asOf);
      if (requestId !== requestSequence.current) return;
      setSummary(loadedSummary);
      setTrends(loadedTrends);
      if (latest && loadedSummary?.asOf) setSelectedDate(loadedSummary.asOf);
      setActiveSection((current) => (
        loadedSummary.sections?.some((section) => section.id === current)
          ? current
          : current === "daily-summary" ? "daily-summary" : loadedSummary.sections?.[0]?.id || "daily-summary"
      ));
    } catch (requestError) {
      if (requestId !== requestSequence.current) return;
      setSummary(null);
      setTrends(null);
      setError({
        unavailable: requestError.status === 404,
        message: requestError.status === 404
          ? "KPI data for this business date has not been published yet."
          : requestError.message || "Published KPI data could not be loaded.",
      });
    } finally {
      await healthPromise;
      if (requestId === requestSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load({ latest: true });
    return () => { requestSequence.current += 1; };
  }, []); // Load once; date changes are handled explicitly below.

  useEffect(() => {
    const refreshLatestOnFocus = () => {
      if (latestMode && document.visibilityState === "visible") load({ latest: true });
    };
    window.addEventListener("focus", refreshLatestOnFocus);
    return () => window.removeEventListener("focus", refreshLatestOnFocus);
  }, [latestMode, load]);

  const section = summary?.sections?.find((item) => item.id === activeSection);
  const allMetrics = useMemo(() => metricMap(summary?.sections), [summary]);
  const selectedTrend = selectedMetric ? trends?.metrics?.[selectedMetric.id] : null;

  const chooseDate = (date) => {
    if (!date) return;
    setSelectedDate(date);
    setLatestMode(false);
    load({ date, latest: false });
  };
  const showLatest = () => {
    setLatestMode(true);
    load({ latest: true });
  };
  const refresh = () => load({ date: selectedDate, latest: latestMode });

  return (
    <div className="kpi-dashboard">
      <div className="kpi-toolbar">
        <div>
          <small>Published Operations KPI</small>
          <h1>Operational performance</h1>
          <p className="kpi-breadcrumb">Colony Ops KPI Dash / Daily Operations / Published reporting</p>
          <p>
            {previewMode
              ? "Representative sample results for visual review. No live operations data is used."
              : "Read-only results from the approved Neon publish model."}
          </p>
        </div>
        <div className="kpi-toolbar-actions">
          <label className="kpi-date-control">
            <span>Business date</span>
            <input aria-label="Business date" type="date" value={selectedDate} onChange={(event) => chooseDate(event.target.value)} />
          </label>
          <button type="button" className="kpi-button kpi-button-quiet" onClick={showLatest} disabled={loading || latestMode}>
            Latest available
          </button>
          <button type="button" className="kpi-button" onClick={refresh} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      <Freshness health={health} message={notice} previewMode={previewMode} latestMode={latestMode} selectedDate={selectedDate} asOf={summary?.asOf} />

      {loading ? (
        <div className="kpi-state">
          <span className="kpi-loader" aria-hidden="true" />
          <strong>Loading published KPI data…</strong>
        </div>
      ) : error ? (
        <div className={`kpi-state ${error.unavailable ? "kpi-state-empty" : "kpi-state-error"}`} role="status">
          <strong>{error.unavailable ? "Not published yet" : "Could not load Operations KPI"}</strong>
          <span>{error.message} No live Epicor data has been substituted.</span>
          {health?.latestSuccessfulPublish && health.latestSuccessfulPublish !== selectedDate && (
            <button type="button" onClick={showLatest}>
              View latest publish ({health.latestSuccessfulPublish})
            </button>
          )}
          <button type="button" className="secondary" onClick={refresh}>Retry</button>
        </div>
      ) : summary ? (
        <>
          <div className="kpi-data-date">
            <span>{previewMode ? "Sample data as of" : "Published data as of"}</span>
            <strong>{formatBusinessDate(summary.asOf)}</strong>
            <small>{previewMode ? "Unsigned sample" : `Neon · ${allMetrics.size} published metrics`}</small>
          </div>

          <section className="kpi-metrics">
            <div className="kpi-section-heading">
              <div><small>Explore</small><h2>KPI sections</h2></div>
              <span>Select a metric for daily or monthly published detail.</span>
            </div>
            <div className="kpi-section-tabs" role="tablist" aria-label="KPI sections">
              <button type="button" role="tab" aria-selected={activeSection === "daily-summary"} className={activeSection === "daily-summary" ? "active" : ""} onClick={() => setActiveSection("daily-summary")}>Daily Summary</button>
              {(summary.sections || []).map((item) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeSection === item.id}
                  className={activeSection === item.id ? "active" : ""}
                  key={item.id}
                  onClick={() => setActiveSection(item.id)}
                >
                  {item.title}
                  <small>{item.metrics?.length || 0}</small>
                </button>
              ))}
            </div>
            {activeSection === "daily-summary" ? (
              <SummaryBlocks
                sections={summary.sections}
                trends={trends}
                selectedMetric={selectedMetric}
                onSelect={setSelectedMetric}
              />
            ) : (
              <SectionMetrics
                section={section}
                trends={trends}
                selectedMetric={selectedMetric}
                onSelect={setSelectedMetric}
              />
            )}
          </section>
        </>
      ) : null}

      {selectedMetric && (
        <KpiDetailPanel
          metric={selectedMetric}
          trend={selectedTrend}
          asOf={summary?.asOf}
          onClose={() => setSelectedMetric(null)}
        />
      )}
    </div>
  );
}