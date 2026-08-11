# PO Detail Report — Architecture & Build Plan

## Current Status (2026-05-08)
Python sync script (`po_detail_report.py`) is built and tested.
Architecture decision on data store / UI layer is **pending**.

---

## What's Built

### Files
| File | Purpose |
|---|---|
| `po_detail_report.py` | Main Python sync script |
| `Run-PODetail-Report.ps1` | PowerShell runner (handles credentials) |
| `PO_History_Master.xlsx` | Output master Excel file (created on first run) |
| `po_checkpoint.json` | Incremental run state (auto-created) |

### Run Modes
```powershell
.\Run-PODetail-Report.ps1 --test    # Current year only — quick pipeline test (~1 min)
.\Run-PODetail-Report.ps1 --full    # Full rebuild year-by-year from 2010
.\Run-PODetail-Report.ps1           # Incremental update (default — run weekly)
```

### Incremental Logic (each weekly run)
1. **New records** — POs with order date >= last max order date
2. **Currently open** — all lines where OpenOrder = true
3. **Last-run open POs** — re-fetch POs that were open last run (catches closures)
4. **Last 6 months** — always refresh regardless of checkpoint

### Master Excel Structure
- **Sheet 1: PO Detail** — all PO line data, updates in place by (PONum + POLine) key
- **Sheet 2: Run Log** — timestamp, mode, added, updated, total rows per run

### Checkpoint File (`po_checkpoint.json`)
```json
{
  "max_order_date": "2026-05-07",
  "open_po_numbers": [123456, 123457, ...]
}
```

---

## BAQ Details
- **BAQ:** `PODetailDashboard_CD`
- **Epicor URL:** `https://epicor.colonydisplay.com/e10live/api/v1/BaqSvc/PODetailDashboard_CD`
- **Auth:** Basic auth via encrypted `Epicor_user.txt` / `Epicor_pwd.txt`
- **Credential helper:** `...\Datalake_Project\Epicor-Cred.ps1`
- **Performance:** ~5.8s per 1000-row batch

### Columns Pulled
| BAQ Field | Label |
|---|---|
| POHeader_PONum | PO Number |
| PODetail_POLine | PO Line |
| POHeader_OrderDate | Order Date |
| Calculated_First_DueDate | Due Date |
| Vendor_VendorID | Vendor ID |
| Vendor_Name | Vendor Name |
| PODetail_PartNum | Part Number |
| PODetail_LineDesc | Description |
| PODetail_ClassID | Class ID |
| PartClass_Description | Class Description |
| PODetail_OrderQty | Order Qty |
| PODetail_DocUnitCost | Unit Cost |
| Calculated_POLineTotal | Line Total |
| Calculated_ReceivedQty | Received Qty |
| PODetail_PUM | PUM |
| POHeader_OpenOrder | Open Order |
| POHeader_EntryPerson | Entry Person |
| POHeader_TermsCode | Terms |
| PORel_TranType | Tran Type |
| PORel_ProjectID | Project ID |

---

## Architecture Decision — Pending

### Problem
The 30MB Excel master file is stranded data — can't be linked from other Excel docs,
can't be searched quickly, and becomes stale immediately.

### Use Case
Estimating team needs **purchase history lookup mid-quote**:
- Search by part number or vendor
- See price history, quantities, trends
- Fast — not a 289s full refresh

### Options Evaluated

#### Option A: SQLite + FastAPI + React (Recommended)
```
Python sync script
    → SQLite (po_history.db)
         ├── FastAPI REST API  →  React search UI  ←  estimators use this
         └── Excel Power Query  ←  ad-hoc analysis
```
- SQLite = single file, zero server, instant row lookups, handles 1M+ rows
- FastAPI = lightweight Python REST API (already have Python)
- React = browser-based search, no Excel needed, no ODBC driver installs
- **Both** interfaces share the same SQLite file

**FastAPI endpoints needed:**
- `GET /parts/{part_num}` — full price history for a part
- `GET /vendors/{vendor_id}` — all POs for a vendor
- `GET /search?q=...` — cross-field search
- `GET /summary/{part_num}` — last paid, avg price, min/max

#### Option B: SQLite + Excel Power Query
- ODBC driver install on each estimator machine (one-time)
- Power Query connects to SQLite, queries return only needed rows
- Estimators stay in Excel — type part number in a cell, hit refresh
- Good fallback if React dashboard isn't wanted

#### Option C: Parquet (Ruled Out)
- Wrong shape for row lookups — built for column scans
- Can't update in place
- No native Excel connector

### Decision Criteria
| Question | Determines |
|---|---|
| Do estimators live in Excel or browser? | Option A vs B |
| Is there a shared network drive or server? | Where SQLite file lives |
| How many estimators? | Matters for concurrent access |

---

## Next Steps (once direction chosen)

### If SQLite + React:
1. Add `write_to_sqlite()` to `po_detail_report.py` (writes same data to `po_history.db`)
2. Build FastAPI app (`po_api.py`) with search endpoints
3. Build React app with part/vendor search UI
4. Run as local service or deploy to internal server

### If SQLite + Power Query:
1. Add `write_to_sqlite()` to `po_detail_report.py`
2. Install SQLite ODBC driver on estimator machines
3. Build Power Query template with parameterized part number lookup
4. Distribute template to estimating team

### SQLite schema (same either way):
```sql
CREATE TABLE po_detail (
    po_num       INTEGER,
    po_line      INTEGER,
    order_date   TEXT,
    due_date     TEXT,
    vendor_id    TEXT,
    vendor_name  TEXT,
    part_num     TEXT,
    description  TEXT,
    class_id     TEXT,
    class_desc   TEXT,
    order_qty    REAL,
    unit_cost    REAL,
    line_total   REAL,
    received_qty REAL,
    pum          TEXT,
    open_order   INTEGER,
    entry_person TEXT,
    terms        TEXT,
    tran_type    TEXT,
    project_id   TEXT,
    PRIMARY KEY (po_num, po_line)
);
CREATE INDEX idx_part_num   ON po_detail(part_num);
CREATE INDEX idx_vendor_id  ON po_detail(vendor_id);
CREATE INDEX idx_order_date ON po_detail(order_date);
```
