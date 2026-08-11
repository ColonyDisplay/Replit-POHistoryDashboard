import os
import re
import sys
import json
import time
import sqlite3
import requests
from pathlib import Path
from datetime import date, datetime, timedelta

SCRIPT_DIR      = Path(__file__).parent
EPICOR_URL      = "https://epicor.colonydisplay.com/e10live/api/v1/BaqSvc/PODetailDashboard_CD"
CHECKPOINT_FILE = SCRIPT_DIR / "po_checkpoint.json"
DB_FILE         = SCRIPT_DIR / "Database" / "po_history.db"

COLUMNS = [
    ("POHeader_PONum",           "PO Number"),
    ("PODetail_POLine",          "PO Line"),
    ("POHeader_OrderDate",       "Order Date"),
    ("Calculated_First_DueDate", "Due Date"),
    ("Vendor_VendorID",          "Vendor ID"),
    ("Vendor_Name",              "Vendor Name"),
    ("PODetail_PartNum",         "Part Number"),
    ("PODetail_LineDesc",        "Description"),
    ("PODetail_ClassID",         "Class ID"),
    ("PartClass_Description",    "Class Description"),
    ("Calculated_OrderedQty",    "Order Qty"),
    ("PODetail_DocUnitCost",     "Unit Cost"),
    ("Calculated_POLineTotal",   "Line Total"),
    ("Calculated_ReceivedQty",   "Received Qty"),
    ("PODetail_PUM",             "Supplier UOM"),
    ("PODetail_IUM",             "Inventory UOM"),
    ("POHeader_OpenOrder",       "Open Order"),
    ("POHeader_EntryPerson",     "Entry Person"),
    ("POHeader_TermsCode",       "Terms"),
    ("PORel_TranType",           "Tran Type"),
    ("PORel_ProjectID",          "Project ID"),
    # Amanda Bland request (2026-06-01): Purchasing Agent name
    # Requires PurAgent table joined in BAQ PODetailDashboard_CD
    # Join: POHeader.Company=PurAgent.Company AND POHeader.BuyerID=PurAgent.PurAgentCode
    ("PurAgent_Name",            "Buyer"),
]

DATE_FIELDS   = {"POHeader_OrderDate", "Calculated_First_DueDate"}
NUMBER_FIELDS = {"Calculated_OrderedQty", "PODetail_DocUnitCost",
                 "Calculated_POLineTotal", "Calculated_ReceivedQty"}

ILLEGAL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def sanitize(val):
    if isinstance(val, str):
        return ILLEGAL_CHARS.sub('', val)
    return val


def parse_epicor_date(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "")).date()
    except Exception:
        return val


def record_to_row(rec):
    row = []
    for field, _ in COLUMNS:
        val = rec.get(field)
        if field in DATE_FIELDS:
            val = parse_epicor_date(val)
        elif field in NUMBER_FIELDS:
            try:
                val = float(val)
            except (TypeError, ValueError):
                pass
        row.append(sanitize(val))
    return row


def get_auth():
    user = os.environ.get("EPICOR_USER")
    pwd  = os.environ.get("EPICOR_PASS")
    if not user or not pwd:
        raise RuntimeError("EPICOR_USER and EPICOR_PASS must be set. Run via Run-PODetail-Report.ps1.")
    return (user, pwd)


def read_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"max_order_date": "1900-01-01", "open_po_numbers": []}


def write_checkpoint(max_order_date, open_po_numbers):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"max_order_date": max_order_date,
                   "open_po_numbers": open_po_numbers}, f)
    print(f"  Checkpoint saved: max_order_date={max_order_date}, "
          f"{len(open_po_numbers)} open POs tracked.", flush=True)


def fetch_paged(auth, filter_expr=None, label="FETCH"):
    params = {"$top": 1000, "$skip": 0}
    if filter_expr:
        params["$filter"] = filter_expr
    records = []
    page = 1
    t_start = time.perf_counter()
    while True:
        print(f"  [{label}] Batch {page} (skip={params['$skip']})...", flush=True)
        t0 = time.perf_counter()
        r = requests.get(EPICOR_URL, auth=auth, params=params, verify=True, timeout=120)
        r.raise_for_status()
        batch = r.json().get("value", [])
        elapsed = time.perf_counter() - t0
        records.extend(batch)
        print(f"  [{label}] Batch {page}: {len(batch)} rows in {elapsed:.1f}s "
              f"(total: {len(records)})", flush=True)
        if len(batch) < 1000:
            break
        params = {"$top": 1000, "$skip": params["$skip"] + 1000}
        if filter_expr:
            params["$filter"] = filter_expr
        page += 1
    print(f"  [{label}] Done: {len(records)} rows in "
          f"{time.perf_counter()-t_start:.1f}s total", flush=True)
    return records


def fetch_incremental(auth, checkpoint):
    max_date      = checkpoint["max_order_date"]
    last_open_pos = checkpoint["open_po_numbers"]
    combined = {}

    print(f"\nStep 1: Fetching new records (order date >= {max_date}) ...", flush=True)
    for rec in fetch_paged(auth, f"POHeader_OrderDate ge datetime'{max_date}T00:00:00'", "NEW"):
        combined[(rec["POHeader_PONum"], rec["PODetail_POLine"])] = rec

    print(f"\nStep 2: Fetching all currently-open PO lines ...", flush=True)
    for rec in fetch_paged(auth, "POHeader_OpenOrder eq true", "OPEN"):
        combined[(rec["POHeader_PONum"], rec["PODetail_POLine"])] = rec

    if last_open_pos:
        print(f"\nStep 3: Re-fetching {len(last_open_pos)} last-run open POs ...", flush=True)
        batch_size = 40
        batches = [last_open_pos[i:i+batch_size]
                   for i in range(0, len(last_open_pos), batch_size)]
        for b_num, batch in enumerate(batches, 1):
            filt = " or ".join(f"POHeader_PONum eq {po}" for po in batch)
            print(f"  [LAST-OPEN] Batch {b_num}/{len(batches)} ({len(batch)} POs)...", flush=True)
            t0 = time.perf_counter()
            r = requests.get(EPICOR_URL, auth=auth,
                             params={"$filter": filt, "$top": 1000},
                             verify=True, timeout=120)
            r.raise_for_status()
            rows = r.json().get("value", [])
            print(f"  [LAST-OPEN] {len(rows)} rows in {time.perf_counter()-t0:.1f}s", flush=True)
            for rec in rows:
                combined[(rec["POHeader_PONum"], rec["PODetail_POLine"])] = rec
    else:
        print("\nStep 3: No last-run open POs in checkpoint, skipping.", flush=True)

    six_months_ago = (date.today() - timedelta(days=183)).isoformat()
    print(f"\nStep 4: Fetching all records from last 6 months "
          f"(order date >= {six_months_ago}) ...", flush=True)
    for rec in fetch_paged(auth,
                           f"POHeader_OrderDate ge datetime'{six_months_ago}T00:00:00'",
                           "6MO"):
        combined[(rec["POHeader_PONum"], rec["PODetail_POLine"])] = rec

    print(f"\nIncremental fetch complete: {len(combined)} unique PO lines.", flush=True)
    return combined


_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS po_detail (
    po_num        INTEGER,
    po_line       INTEGER,
    order_date    TEXT,
    due_date      TEXT,
    vendor_id     TEXT,
    vendor_name   TEXT,
    part_num      TEXT,
    description   TEXT,
    class_id      TEXT,
    class_desc    TEXT,
    order_qty     REAL,
    unit_cost     REAL,
    line_total    REAL,
    received_qty  REAL,
    supplier_uom  TEXT,
    inventory_uom TEXT,
    open_order    INTEGER,
    entry_person  TEXT,
    terms         TEXT,
    tran_type     TEXT,
    project_id    TEXT,
    buyer_name    TEXT,
    PRIMARY KEY (po_num, po_line)
);
CREATE INDEX IF NOT EXISTS idx_part_num   ON po_detail(part_num);
CREATE INDEX IF NOT EXISTS idx_vendor_id  ON po_detail(vendor_id);
CREATE INDEX IF NOT EXISTS idx_order_date ON po_detail(order_date);
CREATE TABLE IF NOT EXISTS run_log (
    run_timestamp   TEXT,
    mode            TEXT,
    records_added   INTEGER,
    records_updated INTEGER,
    total_rows      INTEGER,
    max_order_date  TEXT
);
"""

_SQLITE_UPSERT = """
INSERT OR REPLACE INTO po_detail VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _row_to_sqlite_tuple(row_vals):
    result = []
    for val in row_vals:
        if isinstance(val, (date, datetime)):
            val = str(val)[:10]
        elif isinstance(val, bool):
            val = 1 if val else 0
        result.append(val)
    return tuple(result)


def _migrate_db(conn):
    """Add new columns to existing DB without rebuilding."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(po_detail)").fetchall()}
    migrations = [
        ("buyer_name", "ALTER TABLE po_detail ADD COLUMN buyer_name TEXT"),
    ]
    for col, sql in migrations:
        if col not in existing:
            conn.execute(sql)
            print(f"  DB migration: added column '{col}'", flush=True)
    conn.commit()


def _open_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.executescript(_SQLITE_DDL)
    _migrate_db(conn)
    return conn


def _checkpoint_from_db(conn):
    max_order_date = conn.execute(
        "SELECT COALESCE(MAX(order_date), '1900-01-01') FROM po_detail"
    ).fetchone()[0]
    open_po_numbers = [r[0] for r in conn.execute(
        "SELECT DISTINCT po_num FROM po_detail WHERE open_order = 1"
    ).fetchall()]
    return max_order_date, open_po_numbers


def _write_run_log(conn, mode, added, updated, total, max_order_date):
    conn.execute(
        "INSERT INTO run_log VALUES (?,?,?,?,?,?)",
        (datetime.now().isoformat(), mode, added, updated, total, max_order_date)
    )


def run_full(auth, start_year=2010, end_year=None, mode_label="full"):
    print("=" * 50, flush=True)
    print(f"FULL REBUILD MODE ({mode_label})", flush=True)
    print("=" * 50, flush=True)

    if end_year is None:
        end_year = date.today().year

    conn = _open_db()
    conn.execute("DELETE FROM po_detail")
    conn.commit()

    total = 0
    for year in range(start_year, end_year + 1):
        y_start = f"{year}-01-01"
        y_end   = f"{year + 1}-01-01"
        filt = (f"POHeader_OrderDate ge datetime'{y_start}T00:00:00' and "
                f"POHeader_OrderDate lt datetime'{y_end}T00:00:00'")
        print(f"\n--- Year {year} ---", flush=True)
        records = fetch_paged(auth, filter_expr=filt, label=str(year))

        year_rows = {}
        for rec in records:
            key = (rec["POHeader_PONum"], rec["PODetail_POLine"])
            year_rows[key] = _row_to_sqlite_tuple(record_to_row(rec))
        conn.executemany(_SQLITE_UPSERT, year_rows.values())
        conn.commit()
        total += len(year_rows)
        print(f"  {len(year_rows)} rows written. Running total: {total}", flush=True)

    max_order_date, open_po_numbers = _checkpoint_from_db(conn)
    _write_run_log(conn, mode_label, 0, total, total, max_order_date)
    conn.commit()
    conn.close()

    write_checkpoint(max_order_date, open_po_numbers)
    print(f"\nFull rebuild complete: {total} rows | "
          f"max order date: {max_order_date} | "
          f"open POs: {len(open_po_numbers)}", flush=True)


def run_incremental(auth):
    if not DB_FILE.exists():
        print("Database not found — running full rebuild first.", flush=True)
        run_full(auth)
        return

    print("=" * 50, flush=True)
    print("INCREMENTAL MODE", flush=True)
    print("=" * 50, flush=True)

    checkpoint = read_checkpoint()
    print(f"Checkpoint: max_order_date={checkpoint['max_order_date']}, "
          f"{len(checkpoint['open_po_numbers'])} open POs tracked.", flush=True)

    fetched = fetch_incremental(auth, checkpoint)

    rows = [_row_to_sqlite_tuple(record_to_row(rec)) for rec in fetched.values()]

    conn = _open_db()
    count_before = conn.execute("SELECT COUNT(*) FROM po_detail").fetchone()[0]
    conn.executemany(_SQLITE_UPSERT, rows)
    conn.commit()
    count_after = conn.execute("SELECT COUNT(*) FROM po_detail").fetchone()[0]

    added   = count_after - count_before
    updated = len(rows) - added

    max_order_date, open_po_numbers = _checkpoint_from_db(conn)
    _write_run_log(conn, "incremental", added, updated, count_after, max_order_date)
    conn.commit()
    conn.close()

    write_checkpoint(max_order_date, open_po_numbers)
    print(f"\nIncremental run complete: {added} added | {updated} updated | "
          f"{count_after} total rows | open POs: {len(open_po_numbers)}", flush=True)


def run_backfill_buyers(auth):
    """
    Backfill buyer_name for all existing DB records where buyer_name is NULL.
    Fetches POs in batches from Epicor using just the PO numbers already in the DB.
    Efficient — does not re-download all data, only updates buyer_name.
    """
    print("=" * 50, flush=True)
    print("BACKFILL BUYERS MODE", flush=True)
    print("=" * 50, flush=True)

    conn = _open_db()

    # Get all PO numbers that have at least one line with no buyer
    null_po_nums = [r[0] for r in conn.execute(
        "SELECT DISTINCT po_num FROM po_detail WHERE buyer_name IS NULL OR buyer_name = ''"
    ).fetchall()]

    if not null_po_nums:
        print("No records with missing buyer_name — nothing to backfill.", flush=True)
        conn.close()
        return

    print(f"Found {len(null_po_nums)} POs with missing buyer_name. Fetching from Epicor...",
          flush=True)

    batch_size = 40
    batches    = [null_po_nums[i:i+batch_size]
                  for i in range(0, len(null_po_nums), batch_size)]

    total_updated = 0
    for b_num, batch in enumerate(batches, 1):
        filt = " or ".join(f"POHeader_PONum eq {po}" for po in batch)
        print(f"  [BACKFILL] Batch {b_num}/{len(batches)} ({len(batch)} POs)...",
              flush=True)
        t0 = time.perf_counter()
        r  = requests.get(EPICOR_URL, auth=auth,
                          params={"$filter": filt, "$top": 5000},
                          verify=True, timeout=120)
        r.raise_for_status()
        recs = r.json().get("value", [])
        print(f"  [BACKFILL] Got {len(recs)} rows in {time.perf_counter()-t0:.1f}s", flush=True)

        updates = [
            (sanitize(rec.get("PurAgent_Name")),
             rec["POHeader_PONum"],
             rec["PODetail_POLine"])
            for rec in recs
            if rec.get("PurAgent_Name")
        ]

        if updates:
            conn.executemany(
                "UPDATE po_detail SET buyer_name = ? WHERE po_num = ? AND po_line = ?",
                updates
            )
            conn.commit()
            total_updated += len(updates)
            print(f"  [BACKFILL] Updated {len(updates)} rows.", flush=True)

    conn.close()
    print(f"\nBackfill complete: {total_updated} buyer_name values written "
          f"across {len(null_po_nums)} POs.", flush=True)


def main():
    auth = get_auth()
    if "--test" in sys.argv:
        run_full(auth, start_year=date.today().year,
                 end_year=date.today().year, mode_label="test")
    elif "--full" in sys.argv:
        run_full(auth, start_year=2010)
    elif "--backfill-buyers" in sys.argv:
        run_backfill_buyers(auth)
    else:
        run_incremental(auth)


if __name__ == "__main__":
    main()
