"""
Sync CD-BinInv-FAST Epicor BAQ → SQLite bin_inventory table (full replace).

FIRST RUN — discover actual BAQ column names:
    .\\Run-BinInv-Sync.ps1 --discover

Then update COLUMN_MAP and PRIMARY_KEY below, and sync normally:
    .\\Run-BinInv-Sync.ps1
"""
import os
import re
import sys
import time
import sqlite3
import requests
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

SCRIPT_DIR = Path(__file__).parent
EPICOR_URL = os.environ.get(
    "EPICOR_BININV_BAQ_URL",
    "https://epicor.colonydisplay.com/e10live/api/v1/BaqSvc/CD-BinInv-FAST")
DB_FILE    = SCRIPT_DIR / "Database" / "bin_inventory.db"

# ── Column map: {epicor_field_name: sqlite_column_name}
COLUMN_MAP = OrderedDict([
    ("PartBin_PartNum",       "part_num"),
    ("Part_PartDescription",  "description"),
    ("Warehse_WarehouseCode", "warehouse_code"),
    ("Warehse_Description",   "warehouse_desc"),
    ("PartBin_BinNum",        "bin_num"),
    ("PartBin_OnhandQty",     "on_hand_qty"),       # qty in this bin
    ("PartWhse_OnHandQty",    "warehouse_on_hand"), # total qty across warehouse
    ("Part_IUM",              "uom"),
    ("Part_ClassID",          "class_id"),
])

# Epicor field names to convert to float (returned as strings by this BAQ)
NUMBER_FIELDS = {"PartBin_OnhandQty", "PartWhse_OnHandQty"}

# SQLite column names that form the primary key
PRIMARY_KEY = ("part_num", "warehouse_code", "bin_num")

ILLEGAL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_auth():
    user = os.environ.get("EPICOR_USER")
    pwd  = os.environ.get("EPICOR_PASS")
    if not user or not pwd:
        raise RuntimeError("EPICOR_USER and EPICOR_PASS must be set. Run via Run-BinInv-Sync.ps1.")
    return (user, pwd)


def sanitize(val):
    if isinstance(val, str):
        return ILLEGAL_CHARS.sub("", val)
    return val


def coerce(epicor_field, val):
    if epicor_field in NUMBER_FIELDS:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    if isinstance(val, bool):
        return 1 if val else 0
    return sanitize(val)


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_paged(auth, label="FETCH"):
    """Generator that yields each ~1,000-row Epicor page as it arrives, so the
    caller can stream-and-write instead of buffering the whole result set."""
    params = {"$top": 1000, "$skip": 0}
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
        page += 1
    print(f"  [{label}] Done: {grand_total} rows in "
          f"{time.perf_counter()-t_start:.1f}s total", flush=True)


# ── Discover mode ─────────────────────────────────────────────────────────────

def discover(auth):
    print("=" * 60, flush=True)
    print("DISCOVER MODE — fetching 1 record from CD-BinInv-FAST", flush=True)
    print("=" * 60, flush=True)
    r = requests.get(EPICOR_URL, auth=auth,
                     params={"$top": 1}, verify=True, timeout=120)
    r.raise_for_status()
    records = r.json().get("value", [])
    if not records:
        print("No records returned from BAQ.", flush=True)
        return
    rec = records[0]
    # Filter out OData metadata keys
    fields = {k: v for k, v in rec.items() if not k.startswith("@odata")}
    print(f"\nFound {len(fields)} fields:\n", flush=True)
    print(f"{'Field Name':<40} {'Python Type':<15} {'Sample Value'}", flush=True)
    print("-" * 80, flush=True)
    for key, val in sorted(fields.items()):
        print(f"{key:<40} {type(val).__name__:<15} {repr(val)}", flush=True)
    print("\n" + "=" * 60, flush=True)
    print("Next steps:", flush=True)
    print("  1. Update COLUMN_MAP in bin_inv_sync.py with the field names above", flush=True)
    print("  2. Update NUMBER_FIELDS with any numeric field names", flush=True)
    print("  3. Update PRIMARY_KEY with the unique identifier column names", flush=True)
    print("  4. Run .\\Run-BinInv-Sync.ps1 to sync data", flush=True)


# ── SQLite ────────────────────────────────────────────────────────────────────

def _build_ddl():
    sqlite_cols = list(COLUMN_MAP.values())
    numeric_sqlite = {COLUMN_MAP[k] for k in NUMBER_FIELDS if k in COLUMN_MAP}
    col_defs = []
    for col in sqlite_cols:
        col_type = "REAL" if col in numeric_sqlite else "TEXT"
        col_defs.append(f"    {col:<20} {col_type}")
    pk = ", ".join(PRIMARY_KEY)
    cols_str = ",\n".join(col_defs)
    # Use IF NOT EXISTS — incremental runs keep existing data and upsert changes
    return f"""CREATE TABLE IF NOT EXISTS bin_inventory (
{cols_str},
    last_synced     TEXT,
    PRIMARY KEY ({pk})
);
CREATE INDEX IF NOT EXISTS idx_inv_part ON bin_inventory(part_num);
CREATE INDEX IF NOT EXISTS idx_inv_wh   ON bin_inventory(warehouse_code);
CREATE TABLE IF NOT EXISTS inv_run_log (
    run_timestamp TEXT,
    mode          TEXT,
    upserted      INTEGER,
    total_rows    INTEGER
);"""


def _build_upsert():
    cols = list(COLUMN_MAP.values()) + ["last_synced"]
    cols_str = ", ".join(cols)
    placeholders = ", ".join("?" * len(cols))
    return f"INSERT OR REPLACE INTO bin_inventory ({cols_str}) VALUES ({placeholders})"


def _open_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    return conn


def _ensure_run_log(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            run_timestamp   TEXT,
            mode            TEXT,
            records_added   INTEGER,
            records_updated INTEGER,
            total_rows      INTEGER,
            max_order_date  TEXT
        )
    """)


def record_to_tuple(rec, synced_at):
    return tuple(coerce(field, rec.get(field)) for field in COLUMN_MAP) + (synced_at,)


# ── Write targets (SQLite and Neon/Postgres — see handoff-powerbi.md) ─────────

def _coerce_pg(epicor_field, val):
    if epicor_field in NUMBER_FIELDS:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return sanitize(val)


def _build_pg_upsert():
    cols = list(COLUMN_MAP.values()) + ["last_synced"]
    non_pk = [c for c in cols if c not in PRIMARY_KEY]
    return (
        f"INSERT INTO bin_inventory ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT ({', '.join(PRIMARY_KEY)}) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)
    )


class SqliteTarget:
    name = "sqlite"

    def __init__(self):
        self.conn = _open_db()
        self.conn.executescript(_build_ddl())

    def rows_from_records(self, recs, synced_at):
        return [record_to_tuple(r, synced_at.isoformat()) for r in recs]

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM bin_inventory").fetchone()[0]

    def upsert(self, rows):
        self.conn.executemany(_build_upsert(), rows)
        self.conn.commit()

    def write_run_log(self, synced_at, mode, upserted, total):
        self.conn.execute(
            "INSERT INTO inv_run_log VALUES (?,?,?,?)",
            (synced_at.isoformat(), mode, upserted, total))
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

    def rows_from_records(self, recs, synced_at):
        # Native values for Postgres — no bool→int / datetime→str coercion
        return [tuple(_coerce_pg(f, r.get(f)) for f in COLUMN_MAP) + (synced_at,)
                for r in recs]

    def count(self):
        with self.conn.cursor() as cur:
            return cur.execute("SELECT COUNT(*) FROM bin_inventory").fetchone()[0]

    def upsert(self, rows):
        with self.conn.cursor() as cur:
            cur.executemany(_build_pg_upsert(), rows)
        self.conn.commit()

    def write_run_log(self, synced_at, mode, upserted, total):
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO inv_run_log VALUES (%s,%s,%s,%s)",
                        (synced_at, mode, upserted, total))
        self.conn.commit()

    def close(self):
        self.conn.close()


class NeonHttpTarget:
    """Neon SQL-over-HTTP writer (POST https://<host>/sql, port 443) for hosts
    where outbound 5432 is firewalled. Every request is its own implicit
    session/transaction, so tables are schema-qualified (po_history.*) and
    upserts are batched multi-row INSERT ... ON CONFLICT statements."""
    name = "neon-http"
    # 10 narrow columns/row; 5,000 rows = 50,000 bound params. Verified to fit
    # under Neon's SQL-over-HTTP request-size ceiling; cuts round-trips vs 500.
    # _MAX_PARAMS clamps if columns are added; oversized batches auto-split.
    _BATCH_ROWS = 5000
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
        self._cols = list(COLUMN_MAP.values()) + ["last_synced"]
        self._pk_idx = [self._cols.index(c) for c in PRIMARY_KEY]

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

    def rows_from_records(self, recs, synced_at):
        # JSON-safe values (record_to_tuple already coerces bool -> 0/1)
        return [record_to_tuple(r, synced_at.isoformat()) for r in recs]

    def count(self):
        return int(self._execute(
            "SELECT COUNT(*) FROM po_history.bin_inventory")["rows"][0][0])

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
                f"INSERT INTO po_history.bin_inventory ({', '.join(self._cols)}) "
                f"VALUES {', '.join(values)} "
                f"ON CONFLICT ({', '.join(PRIMARY_KEY)}) DO UPDATE SET {set_clause}",
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
        # A multi-row INSERT ... ON CONFLICT fails if one statement contains
        # duplicate keys, so dedupe by primary key first (last wins, matching
        # the SQLite INSERT OR REPLACE behavior).
        deduped = list({tuple(row[i] for i in self._pk_idx): row
                        for row in rows}.values())
        ncols = len(self._cols)
        non_pk = [c for c in self._cols if c not in PRIMARY_KEY]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)
        batch = self._batch_rows(ncols)
        for i in range(0, len(deduped), batch):
            self._upsert_chunk(deduped[i:i + batch], ncols, set_clause)

    def write_run_log(self, synced_at, mode, upserted, total):
        self._execute(
            "INSERT INTO po_history.inv_run_log VALUES ($1,$2,$3,$4)",
            [synced_at.isoformat(), mode, upserted, total])

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


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync(auth):
    print("=" * 60, flush=True)
    print("BIN INVENTORY SYNC — incremental upsert", flush=True)
    print("=" * 60, flush=True)

    synced_at = datetime.now()
    targets = _make_targets()
    primary = targets[0]
    count_before = primary.count()

    # Stream each page straight to the targets — peak memory stays at ~one page.
    upserted = 0
    for page in fetch_paged(auth, label="BIN-INV"):
        for t in targets:
            t.upsert(t.rows_from_records(page, synced_at))
        upserted += len(page)

    count_after = primary.count()

    for t in targets:
        t.write_run_log(synced_at, "incremental", upserted, count_after)
        t.close()

    print(f"\nSync complete: {upserted} rows upserted | "
          f"{count_before} -> {count_after} total rows in bin_inventory.", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    auth = get_auth()
    if "--discover" in sys.argv:
        discover(auth)
    else:
        sync(auth)


if __name__ == "__main__":
    main()
