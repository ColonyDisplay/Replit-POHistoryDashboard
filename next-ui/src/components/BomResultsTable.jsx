"use client";
import { useState } from "react";

const COLS = [
  { key: "part_num",     label: "Part #" },
  { key: "description",  label: "Description" },
  { key: "vendor_name",  label: "Vendor" },
  { key: "po_num",       label: "PO #" },
  { key: "order_date",   label: "Last PO Date" },
  { key: "order_qty",    label: "Last Qty" },
  { key: "unit_cost",    label: "Unit Cost" },
  { key: "line_total",   label: "Line Total" },
  { key: "on_hand_qty",  label: "Stock on Hand" },
  { key: "open_order",   label: "Open?" },
];

const fmtMoney = (n) =>
  n == null ? "" : Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtQty = (n) =>
  n == null ? "" : Number(n).toLocaleString("en-US", { maximumFractionDigits: 4 });

function downloadCSV(rows) {
  const headers = COLS.map((c) => c.label).join(",");
  const escape = (v) => {
    if (v == null) return "";
    const s = String(v);
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };
  const lines = rows.map((row) =>
    [
      escape(row.part_num),
      escape(row.description),
      escape(row.vendor_name),
      escape(row.po_num),
      escape(row.order_date),
      escape(row.order_qty),
      escape(row.unit_cost),
      escape(row.line_total),
      escape(row.on_hand_qty),
      escape(row.open_order ? "Yes" : ""),
    ].join(",")
  );
  const csv = [headers, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `bom-lookup-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function BomResultsTable({ rows }) {
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
          <strong>{rows.length}</strong> part{rows.length !== 1 ? "s" : ""}
        </p>
        <button className="csv-btn" onClick={() => downloadCSV(sorted)}>
          ⬇ Download CSV
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {COLS.map((c) => (
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
              <tr key={i} className={!row.vendor_name ? "not-found-row" : ""}>
                <td style={{ fontFamily: "monospace", fontWeight: 600, color: row.vendor_name ? "#1f4e79" : "#94a3b8" }}>
                  {row.part_num}
                </td>
                <td>{row.description ?? <span style={{ color: "#94a3b8" }}>Not found</span>}</td>
                <td>{row.vendor_name}</td>
                <td className="num">{row.po_num}</td>
                <td>{row.order_date}</td>
                <td className="num">{fmtQty(row.order_qty)}</td>
                <td className="num">{row.unit_cost != null ? `$${fmtMoney(row.unit_cost)}` : ""}</td>
                <td className="num">{row.line_total != null ? `$${fmtMoney(row.line_total)}` : ""}</td>
                <td className="num" style={{ fontWeight: 700, color: row.on_hand_qty > 0 ? "#16a34a" : "#94a3b8" }}>
                  {row.on_hand_qty != null ? fmtQty(row.on_hand_qty) : ""}
                </td>
                <td className="center">
                  {row.open_order ? <span className="open-badge">OPEN</span> : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
