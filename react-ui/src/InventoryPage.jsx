import { useState, useEffect } from "react";
import { getAllInventory } from "./api";

const INV_COLS = [
  { key: "part_num",          label: "Part #" },
  { key: "description",       label: "Description" },
  { key: "warehouse_code",    label: "Warehouse" },
  { key: "warehouse_desc",    label: "Warehouse Name" },
  { key: "bin_num",           label: "Bin" },
  { key: "on_hand_qty",       label: "Bin Qty" },
  { key: "warehouse_on_hand", label: "WH Total" },
  { key: "uom",               label: "UOM" },
  { key: "class_id",          label: "Class" },
  { key: "last_vendor",       label: "Last Vendor" },
  { key: "last_po_date",      label: "Last PO Date" },
  { key: "last_unit_cost",    label: "Last Unit Cost" },
];

const fmtQty = (n) =>
  n == null ? "" : Number(n).toLocaleString("en-US", { maximumFractionDigits: 4 });

function downloadCSV(rows) {
  const headers = INV_COLS.map((c) => c.label).join(",");
  const escape = (v) => {
    if (v == null) return "";
    const s = String(v);
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };
  const lines = rows.map((row) => INV_COLS.map((c) => escape(row[c.key])).join(","));
  const csv = [headers, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `bin-inventory-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function InventoryTable({ rows }) {
  const [sortCol, setSortCol] = useState("part_num");
  const [sortAsc, setSortAsc] = useState(true);

  if (!rows || rows.length === 0) return null;

  const sorted = [...rows].sort((a, b) => {
    const av = a[sortCol] ?? "";
    const bv = b[sortCol] ?? "";
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortAsc ? cmp : -cmp;
  });

  const handleSort = (col) => {
    if (col === sortCol) setSortAsc((v) => !v);
    else { setSortCol(col); setSortAsc(true); }
  };

  return (
    <div className="table-wrapper">
      <div className="table-toolbar">
        <p className="row-count">
          <strong>{rows.length}</strong> row{rows.length !== 1 ? "s" : ""}
        </p>
        <button className="csv-btn" onClick={() => downloadCSV(sorted)}>
          ⬇ Download CSV
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {INV_COLS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => handleSort(c.key)}
                  className={sortCol === c.key ? "sorted" : ""}
                >
                  {c.label}
                  {sortCol === c.key && (
                    <span className="sort-arrow">{sortAsc ? "▲" : "▼"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={i}>
                <td>{row.part_num}</td>
                <td>{row.description}</td>
                <td>{row.warehouse_code}</td>
                <td>{row.warehouse_desc}</td>
                <td>{row.bin_num}</td>
                <td className="num">{fmtQty(row.on_hand_qty)}</td>
                <td className="num">{fmtQty(row.warehouse_on_hand)}</td>
                <td>{row.uom}</td>
                <td>{row.class_id}</td>
                <td>{row.last_vendor}</td>
                <td>{row.last_po_date}</td>
                <td className="num">{row.last_unit_cost != null ? `$${fmtQty(row.last_unit_cost)}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function InventoryPage() {
  const [allRows, setAllRows] = useState([]);
  const [query, setQuery] = useState("");
  const [boolMode, setBoolMode] = useState("or");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getAllInventory()
      .then((data) => setAllRows(data))
      .catch((err) =>
        setError(
          err.message.includes("Inventory table")
            ? "Inventory not synced — run .\\Run-BinInv-Sync.ps1 first."
            : `API error: ${err.message}`
        )
      )
      .finally(() => setLoading(false));
  }, []);

  const terms = query.trim().toLowerCase().split(",").map((t) => t.trim()).filter(Boolean);
  const getFields = (r) =>
    [r.part_num, r.description, r.warehouse_code, r.warehouse_desc, r.bin_num].map((v) =>
      (v || "").toLowerCase()
    );

  const makeMatcher = (term) => {
    if (!term.includes("*")) return (f) => f.includes(term);
    const parts = term.split("*").map((p) => p.replace(/[.+?^${}()|[\]\\]/g, "\\$&"));
    const rx = new RegExp(parts.join(".*"));
    return (f) => rx.test(f);
  };

  const filteredRows =
    terms.length === 0
      ? allRows
      : allRows.filter((r) => {
          const fields = getFields(r);
          return boolMode === "and"
            ? terms.every((t) => { const m = makeMatcher(t); return fields.some(m); })
            : terms.some((t) => { const m = makeMatcher(t); return fields.some(m); });
        });

  return (
    <>
      <div className="search-wrap">
        <span className="search-icon">🔍</span>
        <input
          type="text"
          placeholder="e.g.  B30*, *hang*, Bartlett — comma-separate, use * as wildcard"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        {loading && <span className="spinner">⟳</span>}
        {query && !loading && (
          <button className="clear-btn" onClick={() => setQuery("")}>
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

      <InventoryTable rows={filteredRows} />

      {!loading && !error && allRows.length > 0 && filteredRows.length === 0 && (
        <p className="no-results">No results for &ldquo;{query}&rdquo;</p>
      )}
    </>
  );
}
