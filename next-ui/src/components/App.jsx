"use client";
import { useState, useEffect, useRef } from "react";
import { UserButton } from "@clerk/react";
import { searchPOs, getPartSummary, getRecentPOs, getMe } from "./api";
import ResultsTable from "./ResultsTable";
import SummaryCard from "./SummaryCard";
import LookupPage from "./LookupPage";
import InventoryPage from "./InventoryPage";
import AdminSection from "./AdminSection";
import OpsKpiDashboard from "./OpsKpiDashboard";
import PanelErrorBoundary from "./PanelErrorBoundary";
import DataLakeDashboard from "./DataLakeDashboard";

// Section keys come from the backend role map; tabs render in this order.
const TAB_DEFS = [
  { id: "search", section: "search", label: "Search" },
  { id: "lookup", section: "bom", label: "BOM Lookup" },
  { id: "inventory", section: "inventory", label: "Inventory" },
  { id: "operations-kpi", section: "operations_kpi", label: "Operations KPI" },
];

function NoAccessScreen({ email }) {
  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1rem",
        padding: "1rem",
        textAlign: "center",
      }}
    >
      <h1 style={{ margin: 0, fontSize: "1.5rem" }}>You don&rsquo;t have access yet</h1>
      <p style={{ margin: 0, color: "#64748b", maxWidth: "30rem" }}>
        You signed in as <strong>{email}</strong>, but this account hasn&rsquo;t
        been granted access to the Colony Epicor Dashboard. Ask an
        administrator to add you.
      </p>
      <UserButton />
    </div>
  );
}

function AdminMenuIcon() {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 13.5V4.3L8 2l5 2.3v9.2" />
      <path d="M1.5 13.5h13M5.5 6.2h.01M8 6.2h.01M10.5 6.2h.01M5.5 8.8h.01M8 8.8h.01M10.5 8.8h.01M7 13.5v-2.2h2v2.2" />
    </svg>
  );
}

function PreviewAdminMenu() {
  return (
    <details className="preview-admin-menu">
      <summary
        className="preview-admin-badge"
        aria-label="Open preview profile menu"
      >
        Preview Admin
      </summary>
      <div className="preview-admin-popover">
        <a href="/admin">
          <AdminMenuIcon />
          <span>
            <strong>Admin</strong>
            <small>Users &amp; access</small>
          </span>
        </a>
        <span className="preview-admin-popover-note">Read-only preview account</span>
      </div>
    </details>
  );
}

export default function App({ previewMode = false, initialPage = "home" }) {
  const [me, setMe] = useState(null);
  const [meError, setMeError] = useState(false);
  const [currentTab, setCurrentTab] = useState(null);
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedPart, setSelectedPart] = useState(null);
  const [summary, setSummary] = useState(null);
  const [boolMode, setBoolMode] = useState("or");
  const debounceRef = useRef(null);

  // Who am I, and which sections can I use?
  useEffect(() => {
    getMe()
      .then((data) => {
        setMe(data);
        if (data.access) {
          setCurrentTab(
            initialPage === "datalake"
              ? "datalake"
              : initialPage === "admin"
                ? "admin"
                : "home",
          );
        }
      })
      .catch(() => setMeError(true));
  }, [initialPage]);

  const sections = me?.access ? me.sections : [];
  const canSearch = sections.includes("search");
  const searchIsOpen = canSearch && currentTab === "search";

  // Load PO data only after the user chooses PO History.
  useEffect(() => {
    if (!searchIsOpen) return;
    getRecentPOs(50).then(setRows).catch(() => {});
  }, [searchIsOpen]);

  useEffect(() => {
    if (!searchIsOpen) return undefined;
    // New search clears the previous part summary (avoids stale card while browsing).
    setSelectedPart(null);
    setSummary(null);
    if (!query.trim()) {
      getRecentPOs(50).then(setRows).catch(() => setRows([]));
      setError(null);
      return;
    }
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchPOs(query.trim(), boolMode);
        setRows(data);
      } catch {
        setError("API error — is the server running?");
        setRows([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }, [query, boolMode, searchIsOpen]);

  const handlePartClick = async (partNum) => {
    setSelectedPart(partNum);
    const s = await getPartSummary(partNum);
    setSummary(s);
  };

  const goHome = () => {
    if (window.location.pathname !== "/") {
      window.location.href = "/";
      return;
    }
    setCurrentTab("home");
  };

  if (meError) {
    return (
      <div style={{ minHeight: "100dvh", display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center", gap: "1rem",
                    padding: "1rem", textAlign: "center" }}>
        <h1 style={{ margin: 0, fontSize: "1.25rem" }}>Something went wrong</h1>
        <p style={{ margin: 0, color: "#64748b" }}>
          Could not verify your access. Reload the page to try again.
        </p>
      </div>
    );
  }

  if (!me) {
    return (
      <div style={{ minHeight: "100dvh", display: "flex", alignItems: "center",
                    justifyContent: "center", color: "#64748b" }}>
        Loading…
      </div>
    );
  }

  if (!me.access) {
    return <NoAccessScreen email={me.email} />;
  }

  const visibleTabs = TAB_DEFS.filter((t) => sections.includes(t.section));
  const canViewPoHistory = sections.includes("search");
  const canViewOperationsKpi = sections.includes("operations_kpi");
  const canManageUsers = sections.includes("users");
  const isPreviewAdmin = Boolean(me.previewMode);
  const samplePreviewMode = isPreviewAdmin && !me.liveData;
  const canViewDataLake = isPreviewAdmin || sections.includes("datalake");
  const visibleDashboardCount = [
    canViewPoHistory,
    canViewOperationsKpi,
    canViewDataLake,
  ].filter(Boolean).length;
  const areaTabs = currentTab === "operations-kpi"
    ? visibleTabs.filter((tab) => tab.id === "operations-kpi")
    : visibleTabs.filter((tab) => tab.id !== "operations-kpi");
  const areaTitle = currentTab === "operations-kpi"
    ? "Operations KPI"
    : currentTab === "datalake"
      ? "DataLake"
    : currentTab === "admin"
      ? "Admin"
    : currentTab === "home"
      ? "Colony Epicor Dashboard"
      : "PO History";
  const areaSubtitle = currentTab === "operations-kpi"
    ? "Published operations metrics, trends, and details"
    : currentTab === "datalake"
      ? "Privileged operational reporting"
    : currentTab === "admin"
      ? "Manage access and administrative settings"
    : currentTab === "home"
      ? "Choose a dashboard to get started"
      : "Search and review purchase order information";

  return (
    <div className="app">
      {previewMode && (
        <div className="preview-mode-banner" role="status">
          Preview admin mode · {me.liveData ? "Live read-only data" : "Representative sample data only"} · User management is read-only · Production sign-in is unchanged
        </div>
      )}
      <header>
        <button
          type="button"
          className="header-home-button"
          onClick={goHome}
          aria-label="Return to dashboard home"
          title="Dashboard home"
        >
          CD
        </button>
        <div className="header-text">
          <h1>{areaTitle}</h1>
          <p className="subtitle">{areaSubtitle}</p>
        </div>
        <div className="header-actions">
          {previewMode ? (
            canManageUsers
              ? <PreviewAdminMenu />
              : <span className="preview-admin-badge">Preview User</span>
          ) : (
            <UserButton>
              {canManageUsers && (
                <UserButton.MenuItems>
                  <UserButton.Link
                    label="Admin"
                    labelIcon={<AdminMenuIcon />}
                    href="/admin"
                  />
                </UserButton.MenuItems>
              )}
            </UserButton>
          )}
        </div>
      </header>

      {currentTab === "admin" && !canManageUsers ? (
        <main className="admin-access-denied">
          <span className="admin-section-kicker">COLONY DISPLAY · ADMINISTRATION</span>
          <h2>Admin access is restricted</h2>
          <p>Your current membership does not include administrative access.</p>
          <button type="button" className="admin-return-button" onClick={goHome}>
            Return to dashboard home
          </button>
        </main>
      ) : currentTab === "datalake" && !canViewDataLake ? (
        <main className="datalake-denied">
          <div className="datalake-kicker">COLONY DISPLAY · RESTRICTED REPORTING</div>
          <h2>DataLake access is restricted</h2>
          <p>Your current membership does not include privileged DataLake reporting. No reporting requests were made.</p>
          <button type="button" className="lake-button" onClick={() => { window.location.href = "/"; }}>Return to dashboard home</button>
        </main>
      ) : (
      <>
      {currentTab !== "home" && currentTab !== "datalake" && currentTab !== "admin" && (
        <div className="tabs">
          <button
            type="button"
            className="tab-btn home-tab-btn"
            onClick={() => setCurrentTab("home")}
          >
            Home
          </button>
          {areaTabs.map((t) => (
            <button
              key={t.id}
              className={`tab-btn ${currentTab === t.id ? "active" : ""}`}
              onClick={() => setCurrentTab(t.id)}
            >
              {t.label}
            </button>
          ))}
          {canViewDataLake && (
            <button type="button" className="tab-btn" onClick={() => { window.location.href = "/datalake"; }}>
              DataLake
            </button>
          )}
        </div>
      )}

      {currentTab === "home" ? (
        <main className="home-panel">
          <div
            className="dashboard-choice-grid"
            data-card-count={visibleDashboardCount}
          >
            {canViewPoHistory && (
              <button
                type="button"
                className="dashboard-choice-card po-history-card"
                onClick={() => setCurrentTab("search")}
              >
                <span className="dashboard-choice-icon" aria-hidden="true">PO</span>
                <span className="dashboard-choice-content">
                  <strong>PO History</strong>
                  <span>Search purchase orders, review pricing, look up BOMs, and check inventory.</span>
                </span>
                <span className="dashboard-choice-arrow" aria-hidden="true">→</span>
              </button>
            )}
            {canViewOperationsKpi && (
              <button
                type="button"
                className="dashboard-choice-card operations-kpi-card"
                onClick={() => setCurrentTab("operations-kpi")}
              >
                <span className="dashboard-choice-icon" aria-hidden="true">KPI</span>
                <span className="dashboard-choice-content">
                  <strong>Operations KPI</strong>
                  <span>Review published operations metrics, trends, and daily details.</span>
                </span>
                <span className="dashboard-choice-arrow" aria-hidden="true">→</span>
              </button>
            )}
            {canViewDataLake && (
              <button
                type="button"
                className="dashboard-choice-card datalake-card"
                onClick={() => { window.location.href = "/datalake"; }}
              >
                <span className="dashboard-choice-icon" aria-hidden="true">DL</span>
                <span className="dashboard-choice-content">
                  <strong>DataLake</strong>
                  <span>Privileged source health, freshness, comparison, and point-in-time inventory reporting.</span>
                </span>
                <span className="dashboard-choice-arrow" aria-hidden="true">→</span>
              </button>
            )}
          </div>
        </main>
      ) : currentTab === "search" ? (
        <div className="tab-panel">
          <div className="search-wrap">
            <span className="search-icon" aria-hidden="true" />
            <input
              type="text"
              placeholder="e.g.  B30*, *widget*, vendor — comma-separate, use * as wildcard"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
            {loading && <span className="spinner">Loading</span>}
            {query && !loading && (
              <button
                className="clear-btn"
                onClick={() => {
                  setQuery("");
                  setSelectedPart(null);
                  setSummary(null);
                }}
              >
                Clear
              </button>
            )}
          </div>

          <div className="bool-toggle">
            <span className="bool-toggle-label">Match:</span>
            <button className={boolMode === "or"  ? "active" : ""} onClick={() => setBoolMode("or")}>Any (OR)</button>
            <button className={boolMode === "and" ? "active" : ""} onClick={() => setBoolMode("and")}>All (AND)</button>
          </div>

          {error && <p className="error">{error}</p>}

          {selectedPart && <SummaryCard partNum={selectedPart} summary={summary} />}

          <ResultsTable rows={rows} onPartClick={handlePartClick} />

          {!loading && query && rows.length === 0 && !error && (
            <p className="no-results">No results for &ldquo;{query}&rdquo;</p>
          )}
        </div>
      ) : currentTab === "lookup" ? (
        <div className="tab-panel">
          <LookupPage />
        </div>
      ) : currentTab === "inventory" ? (
        <div className="tab-panel">
          <InventoryPage />
        </div>
      ) : currentTab === "operations-kpi" ? (
        <div className="tab-panel kpi-tab-panel">
          <PanelErrorBoundary>
            <OpsKpiDashboard previewMode={samplePreviewMode} />
          </PanelErrorBoundary>
        </div>
      ) : currentTab === "datalake" ? (
        <PanelErrorBoundary>
          <DataLakeDashboard previewMode={samplePreviewMode} onReturnHome={() => { window.location.href = "/"; }} />
        </PanelErrorBoundary>
      ) : currentTab === "admin" ? (
        <AdminSection meEmail={me.email} previewMode={previewMode} />
      ) : null}
      </>
      )}
    </div>
  );
}
