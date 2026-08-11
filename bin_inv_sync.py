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
EPICOR_URL = "https://epicor.colonydisplay.com/e10live/api/v1/BaqSvc/CD-BinInv-FAST"
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
    params = {"$top": 1000, "$skip": 0}
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
        page += 1
    print(f"  [{label}] Done: {len(records)} rows in "
          f"{time.perf_counter()-t_start:.1f}s total", flush=True)
    return records


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


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync(auth):
    print("=" * 60, flush=True)
    print("BIN INVENTORY SYNC — incremental upsert", flush=True)
    print("=" * 60, flush=True)

    records = fetch_paged(auth, label="BIN-INV")
    synced_at = datetime.now().isoformat()

    print(f"\nBuilding rows...", flush=True)
    rows = [record_to_tuple(r, synced_at) for r in records]

    conn = _open_db()
    conn.executescript(_build_ddl())

    count_before = conn.execute("SELECT COUNT(*) FROM bin_inventory").fetchone()[0]

    upsert_sql = _build_upsert()
    conn.executemany(upsert_sql, rows)

    count_after = conn.execute("SELECT COUNT(*) FROM bin_inventory").fetchone()[0]
    upserted = len(rows)

    conn.execute(
        "INSERT INTO inv_run_log VALUES (?,?,?,?)",
        (synced_at, "incremental", upserted, count_after)
    )
    conn.commit()
    conn.close()

    print(f"\nSync complete: {upserted} rows upserted | "
          f"{count_before} → {count_after} total rows in bin_inventory.", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    auth = get_auth()
    if "--discover" in sys.argv:
        discover(auth)
    else:
        sync(auth)


if __name__ == "__main__":
    main()
