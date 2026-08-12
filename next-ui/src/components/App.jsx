"use client";
import { useState, useEffect, useRef } from "react";
import { UserButton } from "@clerk/react";
import { searchPOs, getPartSummary, getRecentPOs } from "./api";
import ResultsTable from "./ResultsTable";
import SummaryCard from "./SummaryCard";
import LookupPage from "./LookupPage";
import InventoryPage from "./InventoryPage";

export default function App() {
  const [currentTab, setCurrentTab] = useState("search");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedPart, setSelectedPart] = useState(null);
  const [summary, setSummary] = useState(null);
  const [boolMode, setBoolMode] = useState("or");
  const debounceRef = useRef(null);

  // Load 50 most recent on initial mount
  useEffect(() => {
    getRecentPOs(50).then(setRows).catch(() => {});
  }, []);

  useEffect(() => {
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
  }, [query, boolMode]);

  const handlePartClick = async (partNum) => {
    setSelectedPart(partNum);
    const s = await getPartSummary(partNum);
    setSummary(s);
  };

  return (
    <div className="app">
      <header>
        <div className="header-icon">📋</div>
        <div className="header-text">
          <h1>PO Price History</h1>
          <p className="subtitle">Search and lookup purchase order data</p>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <UserButton />
        </div>
      </header>

      <div className="tabs">
        <button
          className={`tab-btn ${currentTab === "search" ? "active" : ""}`}
          onClick={() => setCurrentTab("search")}
        >
          Search
        </button>
        <button
          className={`tab-btn ${currentTab === "lookup" ? "active" : ""}`}
          onClick={() => setCurrentTab("lookup")}
        >
          BOM Lookup
        </button>
        <button
          className={`tab-btn ${currentTab === "inventory" ? "active" : ""}`}
          onClick={() => setCurrentTab("inventory")}
        >
          Inventory
        </button>
      </div>

      {currentTab === "search" ? (
        <div className="tab-panel">
          <div className="search-wrap">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              placeholder="e.g.  B30*, *widget*, vendor — comma-separate, use * as wildcard"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
            {loading && <span className="spinner">⟳</span>}
            {query && !loading && (
              <button
                className="clear-btn"
                onClick={() => {
                  setQuery("");
                  setSelectedPart(null);
                  setSummary(null);
                }}
              >
                ✕
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
      ) : (
        <div className="tab-panel">
          <InventoryPage />
        </div>
      )}
    </div>
  );
}
