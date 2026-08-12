export default function SummaryCard({ partNum, summary }) {
  if (!summary) return null;

  const fmt = (n) =>
    n == null ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtQty = (n) =>
    n == null ? "—" : Number(n).toLocaleString("en-US");

  return (
    <div className="summary-card">
      <h3>Price Summary — {partNum}</h3>
      <div className="summary-grid">
        <div className="summary-stat">
          <span className="label">Last Order</span>
          <span className="value">{summary.last_order_date ?? "—"}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Avg Unit Cost</span>
          <span className="value money">${fmt(summary.avg_unit_cost)}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Min Unit Cost</span>
          <span className="value money">${fmt(summary.min_unit_cost)}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Max Unit Cost</span>
          <span className="value money">${fmt(summary.max_unit_cost)}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Std Mtl Cost</span>
          <span className="value money">${fmt(summary.std_mtl_cost)}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Avg Mtl Cost</span>
          <span className="value money">${fmt(summary.avg_mtl_cost)}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Total Qty Ordered</span>
          <span className="value">{fmtQty(summary.total_qty)}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Total PO Lines</span>
          <span className="value">{summary.total_orders}</span>
        </div>
      </div>
    </div>
  );
}
