import { useRef, useMemo, useCallback } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
} from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

const fmtMoney = (p) =>
  p.value == null ? "" : "$" + Number(p.value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const openBadge = (p) =>
  p.value ? '<span style="background:#2563eb;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">OPEN</span>' : "";

const COL_DEFS = [
  { field: "part_num",     headerName: "Part #",      filter: "agTextColumnFilter",   cellStyle: { color: "#2563eb", cursor: "pointer" }, width: 130 },
  { field: "description",  headerName: "Description", filter: "agTextColumnFilter",   flex: 2 },
  { field: "vendor_name",  headerName: "Vendor",      filter: "agTextColumnFilter",   flex: 1 },
  { field: "po_num",       headerName: "PO #",        filter: "agNumberColumnFilter", width: 90,  type: "numericColumn" },
  { field: "order_date",   headerName: "Order Date",  filter: "agDateColumnFilter",   width: 120, sort: "desc" },
  { field: "order_qty",    headerName: "Qty",         filter: "agNumberColumnFilter", width: 80,  type: "numericColumn" },
  { field: "supplier_uom", headerName: "UoM",         filter: "agTextColumnFilter",   width: 75  },    // Amanda
  { field: "unit_cost",    headerName: "Unit Cost",   filter: "agNumberColumnFilter", width: 105, type: "numericColumn", valueFormatter: fmtMoney },
  { field: "line_total",   headerName: "Line Total",  filter: "agNumberColumnFilter", width: 110, type: "numericColumn", valueFormatter: fmtMoney },
  { field: "buyer_name",   headerName: "Buyer",       filter: "agTextColumnFilter",   width: 120 },     // Amanda
  { field: "project_id",   headerName: "Project ID",  filter: "agTextColumnFilter",   width: 110 },     // Amanda
  { field: "open_order",   headerName: "Open?",       filter: "agTextColumnFilter",   width: 80,  cellRenderer: (p) => p.value ? "OPEN" : "", cellStyle: (p) => p.value ? { color: "#2563eb", fontWeight: 600 } : {} },
];

const DEFAULT_COL = {
  sortable: true,
  resizable: true,
  suppressHeaderMenuButton: false,  // filter icon in header opens dropdown
};

export default function ResultsTable({ rows, onPartClick }) {
  const gridRef = useRef();

  const theme = useMemo(
    () =>
      themeQuartz.withParams({
        accentColor: "#2563eb",
        headerBackgroundColor: "#1e3a5f",
        headerTextColor: "#ffffff",
        rowHoverColor: "#eff6ff",
        fontFamily: "inherit",
        fontSize: 13,
      }),
    []
  );

  const onCellClicked = useCallback(
    (e) => {
      if (e.colDef.field === "part_num" && e.value) onPartClick(e.value);
    },
    [onPartClick]
  );

  const onExportCSV = useCallback(() => {
    gridRef.current?.api.exportDataAsCsv({
      fileName: `po-results-${new Date().toISOString().slice(0, 10)}.csv`,
    });
  }, []);

  if (!rows || rows.length === 0) return null;

  return (
    <div className="table-wrapper">
      <div className="table-toolbar">
        <p className="row-count">
          <strong>{rows.length}</strong> row{rows.length !== 1 ? "s" : ""}
        </p>
        <button className="csv-btn" onClick={onExportCSV}>
          ⬇ Download CSV
        </button>
      </div>
      <div style={{ height: 520, width: "100%" }}>
        <AgGridReact
          ref={gridRef}
          theme={theme}
          rowData={rows}
          columnDefs={COL_DEFS}
          defaultColDef={DEFAULT_COL}
          onCellClicked={onCellClicked}
          pagination={true}
          paginationPageSize={100}
          paginationPageSizeSelector={[50, 100, 250, 500]}
          rowSelection="multiple"
          suppressRowClickSelection={true}
        />
      </div>
    </div>
  );
}
