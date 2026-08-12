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
EPICOR_URL      = os.environ.get(
    "EPICOR_PO_BAQ_URL",
    "https://epicor.colonydisplay.com/e10live/api/v1/BaqSvc/PODetailDashboard_CD")
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


def write_checkpoint(max_order_date, open_po_numbers):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"max_order_date": max_order_date,
                   "open_po_numbers": open_po_numbers}, f)
    print(f"  Checkpoint saved: max_order_date={max_order_date}, "
          f"{len(open_po_numbers)} open POs tracked.", flush=True)


def fetch_paged(auth, filter_expr=None, label="FETCH"):
    """Generator that yields each ~1,000-row Epicor page as it arrives, so
    callers can stream-and-write instead of holding the whole result set in
    memory. Peak memory stays at ~one page regardless of dataset size."""
    params = {"$top": 1000, "$skip": 0}
    if filter_expr:
        params["$filter"] = filter_expr
    page = 1
    grand_total = 0
    t_start = time.perf_counter()
    while True:
        print(f"  [{label}] Batch {page} (skip={params['$skip']})...", flush=True)
        t0 = time.perf_counter()
        r = requests.get(EPICOR_URL, auth=auth, params=params, verify=True, timeout=120)
        r.raise_for_status()
        batch = r.json().get("value", [])
        elapsed = time.perf_counter() - t0
        grand_total += len(batch)
        print(f"  [{label}] Batch {page}: {len(batch)} rows in {elapsed:.1f}s "
              f"(total: {grand_total})", flush=True)
        if batch:
            yield batch
        if len(batch) < 1000:
            break
        params = {"$top": 1000, "$skip": params["$skip"] + 1000}
        if filter_expr:
            params["$filter"] = filter_expr
        page += 1
    print(f"  [{label}] Done: {grand_total} rows in "
          f"{time.perf_counter()-t_start:.1f}s total", flush=True)


def _dedupe_by_key(records):
    """Collapse to the last record per (PO number, PO line) — mirrors the
    year-level dict dedup the streaming rebuild replaces. Required because a
    multi-row INSERT ... ON CONFLICT cannot touch the same key twice in one
    statement."""
    deduped = {}
    for rec in records:
        deduped[(rec["POHeader_PONum"], rec["PODetail_POLine"])] = rec
    return list(deduped.values())


def fetch_incremental(auth, checkpoint):
    max_date      = checkpoint["max_order_date"]
    last_open_pos = checkpoint["open_po_numbers"]
    combined = {}

    print(f"\nStep 1: Fetching new records (order date >= {max_date}) ...", flush=True)
    for page in fetch_paged(auth, f"POHeader_OrderDate ge datetime'{max_date}T00:00:00'", "NEW"):
        for rec in page:
            combined[(rec["POHeader_PONum"], rec["PODetail_POLine"])] = rec

    print(f"\nStep 2: Fetching all currently-open PO lines ...", flush=True)
    for page in fetch_paged(auth, "POHeader_OpenOrder eq true", "OPEN"):
        for rec in page:
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
    for page in fetch_paged(auth,
                            f"POHeader_OrderDate ge datetime'{six_months_ago}T00:00:00'",
                            "6MO"):
        for rec in page:
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


# ── Write targets (SQLite and Neon/Postgres — see handoff-powerbi.md) ─────────

_PG_COLUMNS = [
    "po_num", "po_line", "order_date", "due_date", "vendor_id", "vendor_name",
    "part_num", "description", "class_id", "class_desc", "order_qty",
    "unit_cost", "line_total", "received_qty", "supplier_uom", "inventory_uom",
    "open_order", "entry_person", "terms", "tran_type", "project_id",
    "buyer_name",
]

_PG_UPSERT = (
    f"INSERT INTO po_detail ({', '.join(_PG_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(_PG_COLUMNS))}) "
    "ON CONFLICT (po_num, po_line) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}"
                for c in _PG_COLUMNS if c not in ("po_num", "po_line"))
)


class SqliteTarget:
    name = "sqlite"

    def __init__(self):
        self.conn = _open_db()

    def rows_from_records(self, recs):
        # SQLite stores dates as 'YYYY-MM-DD' text and booleans as 0/1
        return [_row_to_sqlite_tuple(record_to_row(rec)) for rec in recs]

    def delete_all(self):
        self.conn.execute("DELETE FROM po_detail")
        self.conn.commit()

    def upsert(self, rows):
        self.conn.executemany(_SQLITE_UPSERT, rows)
        self.conn.commit()

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM po_detail").fetchone()[0]

    def checkpoint(self):
        return _checkpoint_from_db(self.conn)

    def pos_missing_buyer(self):
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT po_num FROM po_detail "
            "WHERE buyer_name IS NULL OR buyer_name = ''").fetchall()]

    def update_buyers(self, updates):
        self.conn.executemany(
            "UPDATE po_detail SET buyer_name = ? WHERE po_num = ? AND po_line = ?",
            updates)
        self.conn.commit()

    def write_run_log(self, mode, added, updated, total, max_order_date):
        _write_run_log(self.conn, mode, added, updated, total, max_order_date)
        self.conn.commit()

    def close(self):
        self.conn.close()


class PostgresTarget:
    """Neon/Postgres writer. Schema is managed by neon-schema.sql — this
    class performs no DDL (see handoff-powerbi.md). All pipeline tables live
    in the dedicated po_history schema (the Neon database is shared)."""
    name = "postgres"

    def __init__(self, dsn):
        import psycopg
        self.conn = psycopg.connect(dsn)
        self.conn.execute("SET search_path TO po_history")

    def rows_from_records(self, recs):
        # Postgres takes native date/bool values — no SQLite coercion
        return [tuple(record_to_row(rec)) for rec in recs]

    def delete_all(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM po_detail")
        self.conn.commit()

    def upsert(self, rows):
        with self.conn.cursor() as cur:
            cur.executemany(_PG_UPSERT, rows)
        self.conn.commit()

    def count(self):
        with self.conn.cursor() as cur:
            return cur.execute("SELECT COUNT(*) FROM po_detail").fetchone()[0]

    def checkpoint(self):
        with self.conn.cursor() as cur:
            max_order_date = cur.execute(
                "SELECT COALESCE(MAX(order_date), DATE '1900-01-01') FROM po_detail"
            ).fetchone()[0]
            open_po_numbers = [r[0] for r in cur.execute(
                "SELECT DISTINCT po_num FROM po_detail WHERE open_order"
            ).fetchall()]
        return str(max_order_date), open_po_numbers

    def pos_missing_buyer(self):
        with self.conn.cursor() as cur:
            return [r[0] for r in cur.execute(
                "SELECT DISTINCT po_num FROM po_detail "
                "WHERE buyer_name IS NULL OR buyer_name = ''").fetchall()]

    def update_buyers(self, updates):
        with self.conn.cursor() as cur:
            cur.executemany(
                "UPDATE po_detail SET buyer_name = %s "
                "WHERE po_num = %s AND po_line = %s", updates)
        self.conn.commit()

    def write_run_log(self, mode, added, updated, total, max_order_date):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO run_log VALUES (%s,%s,%s,%s,%s,%s)",
                (datetime.now(), mode, added, updated, total, max_order_date))
        self.conn.commit()

    def close(self):
        self.conn.close()


class NeonHttpTarget:
    """Neon SQL-over-HTTP writer (POST https://<host>/sql, port 443) for hosts
    where outbound 5432 is firewalled. Every request is its own implicit
    session/transaction, so tables are schema-qualified (po_history.*) and
    upserts are batched multi-row INSERT ... ON CONFLICT statements."""
    name = "neon-http"
    # po_detail rows are wide (long text), so the binding constraint is Neon's
    # SQL-over-HTTP request body size, NOT PG's 65,535 param limit: ~1,200 wide
    # rows/request is the measured ceiling. 1,000 rows (22,000 params) keeps a
    # safe margin while cutting round-trips vs the old 500. Oversized batches
    # auto-split in _upsert_chunk, so correctness holds regardless.
    _BATCH_ROWS = 1000
    _MAX_PARAMS = 60000
    _MIN_SPLIT = 100

    def __init__(self, dsn):
        from urllib.parse import urlparse
        self.endpoint = f"https://{urlparse(dsn).hostname}/sql"
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Neon-Connection-String": dsn,
            "Neon-Raw-Text-Output": "true",
            "Neon-Array-Mode": "true",
        })

    def _execute(self, query, params=None):
        body = {"query": query, "params": params or []}
        last_err = None
        for delay in (0, 1, 3):
            if delay:
                time.sleep(delay)
            try:
                r = self.session.post(self.endpoint, json=body, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_err = exc
                continue
            if r.status_code >= 500:
                last_err = RuntimeError(f"Neon HTTP {r.status_code}: {r.text[:200]}")
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Neon HTTP {r.status_code}: {r.text[:500]}")
            return r.json()
        raise last_err

    def rows_from_records(self, recs):
        # JSON-safe values: dates as 'YYYY-MM-DD' text, bools as 0/1 —
        # Postgres casts both to the target column types.
        return [_row_to_sqlite_tuple(record_to_row(rec)) for rec in recs]

    def delete_all(self):
        self._execute("DELETE FROM po_history.po_detail")

    @staticmethod
    def _is_too_large(exc):
        # Neon's HTTP proxy rejects oversized request bodies with either a 413
        # or a generic 'HTTP 400: Database request failed' (empty code/detail).
        # Genuine SQL errors carry a real PG code/detail, so they won't match.
        msg = str(exc).lower()
        if any(s in msg for s in ("413", "too large", "request entity", "payload")):
            return True
        return "http 400" in msg and "database request failed" in msg

    def _batch_rows(self, ncols):
        return max(1, min(self._BATCH_ROWS, self._MAX_PARAMS // ncols))

    def _upsert_chunk(self, chunk, ncols, set_clause):
        if not chunk:
            return
        values, params = [], []
        for r_i, row in enumerate(chunk):
            base = r_i * ncols
            values.append("(" + ",".join(f"${base + c + 1}" for c in range(ncols)) + ")")
            params.extend(row)
        try:
            self._execute(
                f"INSERT INTO po_history.po_detail ({', '.join(_PG_COLUMNS)}) "
                f"VALUES {', '.join(values)} "
                f"ON CONFLICT (po_num, po_line) DO UPDATE SET {set_clause}",
                params)
        except RuntimeError as exc:
            # Payload rejected for size: split the chunk and retry each half.
            # Stop splitting below _MIN_SPLIT so a genuine error fails fast.
            if len(chunk) > self._MIN_SPLIT and self._is_too_large(exc):
                mid = len(chunk) // 2
                self._upsert_chunk(chunk[:mid], ncols, set_clause)
                self._upsert_chunk(chunk[mid:], ncols, set_clause)
            else:
                raise

    def upsert(self, rows):
        rows = list(rows)
        ncols = len(_PG_COLUMNS)
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}"
                               for c in _PG_COLUMNS if c not in ("po_num", "po_line"))
        batch = self._batch_rows(ncols)
        for i in range(0, len(rows), batch):
            self._upsert_chunk(rows[i:i + batch], ncols, set_clause)

    def count(self):
        return int(self._execute(
            "SELECT COUNT(*) FROM po_history.po_detail")["rows"][0][0])

    def checkpoint(self):
        max_order_date = self._execute(
            "SELECT COALESCE(MAX(order_date), DATE '1900-01-01') "
            "FROM po_history.po_detail")["rows"][0][0]
        open_po_numbers = [int(r[0]) for r in self._execute(
            "SELECT DISTINCT po_num FROM po_history.po_detail WHERE open_order"
        )["rows"]]
        return str(max_order_date)[:10], open_po_numbers

    def pos_missing_buyer(self):
        return [int(r[0]) for r in self._execute(
            "SELECT DISTINCT po_num FROM po_history.po_detail "
            "WHERE buyer_name IS NULL OR buyer_name = ''")["rows"]]

    def update_buyers(self, updates):
        updates = list(updates)
        for i in range(0, len(updates), self._BATCH_ROWS):
            chunk = updates[i:i + self._BATCH_ROWS]
            values, params = [], []
            for r_i, (buyer, po, line) in enumerate(chunk):
                base = r_i * 3
                values.append(f"(${base + 1}::text, ${base + 2}::int, ${base + 3}::int)")
                params.extend([buyer, po, line])
            self._execute(
                "UPDATE po_history.po_detail AS t SET buyer_name = v.buyer "
                f"FROM (VALUES {', '.join(values)}) AS v(buyer, po, line) "
                "WHERE t.po_num = v.po AND t.po_line = v.line",
                params)

    def write_run_log(self, mode, added, updated, total, max_order_date):
        self._execute(
            "INSERT INTO po_history.run_log VALUES ($1,$2,$3,$4,$5,$6)",
            [datetime.now().isoformat(), mode, added, updated, total,
             str(max_order_date)[:10]])

    def close(self):
        self.session.close()


def _neon_transport(dsn):
    """'http' when NEON_HTTP=1 or when outbound 5432 is blocked (firewall);
    'psycopg' when a quick TCP probe to the Postgres port succeeds."""
    if os.environ.get("NEON_HTTP") == "1":
        return "http"
    import socket
    from urllib.parse import urlparse
    u = urlparse(dsn)
    try:
        socket.create_connection((u.hostname, u.port or 5432), timeout=3).close()
        return "psycopg"
    except OSError:
        return "http"


def _make_targets():
    """DATABASE_URL set -> Neon (psycopg over 5432, or SQL-over-HTTP on 443
    when 5432 is blocked), plus SQLite when DUAL_WRITE=1; otherwise the
    existing SQLite path. Per handoff-powerbi.md."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return [SqliteTarget()]
    if _neon_transport(dsn) == "http":
        targets = [NeonHttpTarget(dsn)]
    else:
        targets = [PostgresTarget(dsn)]
    if os.environ.get("DUAL_WRITE") == "1":
        targets.append(SqliteTarget())
    print(f"Write targets: {', '.join(t.name for t in targets)}", flush=True)
    return targets


def run_full(auth, start_year=2010, end_year=None, mode_label="full", targets=None):
    print("=" * 50, flush=True)
    print(f"FULL REBUILD MODE ({mode_label})", flush=True)
    print("=" * 50, flush=True)

    if end_year is None:
        end_year = date.today().year

    if targets is None:
        targets = _make_targets()
    for t in targets:
        t.delete_all()

    written = 0
    for year in range(start_year, end_year + 1):
        y_start = f"{year}-01-01"
        y_end   = f"{year + 1}-01-01"
        filt = (f"POHeader_OrderDate ge datetime'{y_start}T00:00:00' and "
                f"POHeader_OrderDate lt datetime'{y_end}T00:00:00'")
        print(f"\n--- Year {year} ---", flush=True)

        # Stream each page straight to the targets — only one page is held in
        # memory at a time. Dedup within the page (upserts across pages are
        # idempotent, so the last write for a key wins, same as before).
        year_written = 0
        for page in fetch_paged(auth, filter_expr=filt, label=str(year)):
            recs = _dedupe_by_key(page)
            for t in targets:
                t.upsert(t.rows_from_records(recs))
            year_written += len(recs)
        written += year_written
        print(f"  {year_written} rows written. Running total (pages): {written}",
              flush=True)

    # Authoritative row count comes from the database, so cross-page duplicate
    # keys are never double-counted in the run log.
    total = targets[0].count()
    max_order_date, open_po_numbers = targets[0].checkpoint()
    for t in targets:
        t.write_run_log(mode_label, 0, total, total, max_order_date)
        t.close()

    write_checkpoint(max_order_date, open_po_numbers)
    print(f"\nFull rebuild complete: {total} rows | "
          f"max order date: {max_order_date} | "
          f"open POs: {len(open_po_numbers)}", flush=True)


def run_incremental(auth):
    targets = _make_targets()
    primary = targets[0]

    if primary.count() == 0:
        print("Database is empty — running full rebuild first.", flush=True)
        run_full(auth, targets=targets)
        return

    print("=" * 50, flush=True)
    print("INCREMENTAL MODE", flush=True)
    print("=" * 50, flush=True)

    # Checkpoint state is derived from the database itself, so no checkpoint
    # file needs to move between machines (see handoff-powerbi.md).
    max_order_date, open_po_numbers = primary.checkpoint()
    checkpoint = {"max_order_date": max_order_date,
                  "open_po_numbers": open_po_numbers}
    print(f"Checkpoint (from {primary.name}): max_order_date={max_order_date}, "
          f"{len(open_po_numbers)} open POs tracked.", flush=True)

    fetched = fetch_incremental(auth, checkpoint)

    count_before = primary.count()
    for t in targets:
        t.upsert(t.rows_from_records(fetched.values()))
    count_after = primary.count()

    added   = count_after - count_before
    updated = len(fetched) - added

    max_order_date, open_po_numbers = primary.checkpoint()
    for t in targets:
        t.write_run_log("incremental", added, updated, count_after, max_order_date)
        t.close()

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

    targets = _make_targets()

    # Get all PO numbers that have at least one line with no buyer
    null_po_nums = targets[0].pos_missing_buyer()

    if not null_po_nums:
        print("No records with missing buyer_name — nothing to backfill.", flush=True)
        for t in targets:
            t.close()
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
            for t in targets:
                t.update_buyers(updates)
            total_updated += len(updates)
            print(f"  [BACKFILL] Updated {len(updates)} rows.", flush=True)

    for t in targets:
        t.close()
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
