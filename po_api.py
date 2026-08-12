import os
import asyncio
import subprocess
import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# ── Configuration ──────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ENABLE_SCRIPT_RUNNER = os.environ.get("ENABLE_SCRIPT_RUNNER", "0") == "1"
REACT_DIST = Path(__file__).parent / "react-ui" / "dist"

# ── Connection pool ────────────────────────────────────────────────────────────
# Pool is created at startup; lazy=True lets the app start before DATABASE_URL
# is populated (e.g. during local dev without secrets).

pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    global pool
    if pool is None:
        if not DATABASE_URL:
            raise HTTPException(
                status_code=503,
                detail="DATABASE_URL is not configured — add it to Replit Secrets",
            )
        pool = ConnectionPool(
            DATABASE_URL,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
            open=True,
        )
    return pool


def get_conn():
    """Dependency / helper — yields a connection from the pool."""
    p = get_pool()
    with p.connection() as conn:
        yield conn


# ── Script runner — Windows-only; disabled on Replit ──────────────────────────

PROJECTS_ROOT = Path(r"C:\VSCode_Projects\Colony-Projects")

SCRIPT_WHITELIST = {
    "sf-epicor-audit": PROJECTS_ROOT / "sf-epicor_sync_audit" / "Run-SFEpicorAudit.ps1",
    "sf-epicor-audit-dry": PROJECTS_ROOT / "sf-epicor_sync_audit" / "Run-SFEpicorAudit.ps1",
    "po-detail-sync": Path(r"C:\VSCode_Projects\Colony-Projects\PO-History-Detail-SQLLite\Run-PODetail-Report.ps1"),
    "bin-inv-sync": Path(r"C:\VSCode_Projects\Colony-Projects\PO-History-Detail-SQLLite\Run-BinInv-Sync.ps1"),
}

SCRIPT_ARGS = {
    "sf-epicor-audit-dry": ["--dry-run"],
}


class RunScriptRequest(BaseModel):
    script_id: str
    extra_args: Optional[List[str]] = None


class BulkLookupRequest(BaseModel):
    part_numbers: List[str]


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Colony PO History API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174",
                   "http://localhost:8000", "http://localhost:8067"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── PO history endpoints ───────────────────────────────────────────────────────

@app.get("/recent")
def get_recent(limit: int = 50, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_detail ORDER BY order_date DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return rows


@app.get("/health")
def health(conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT COUNT(*) AS rows, MAX(order_date) AS max_order_date FROM po_detail"
    ).fetchone()
    max_date = row["max_order_date"]
    age_days = (datetime.date.today() - max_date).days if max_date else None
    return {
        "status": "ok",
        "rows": row["rows"],
        "max_order_date": str(max_date) if max_date else None,
        "data_age_days": age_days,
    }


@app.get("/parts/{part_num}")
def get_part_history(part_num: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_detail WHERE part_num = %s ORDER BY order_date DESC",
        (part_num,),
    ).fetchall()
    return rows


@app.get("/vendors/{vendor_id}")
def get_vendor_history(vendor_id: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_detail WHERE vendor_id = %s ORDER BY order_date DESC",
        (vendor_id,),
    ).fetchall()
    return rows


@app.get("/search")
def search(q: str = Query(..., min_length=1), mode: str = Query("or"),
           conn=Depends(get_conn)):
    terms = [t.strip() for t in q.split(",") if t.strip()]
    fields = ["part_num", "vendor_name", "description"]
    # ILIKE for case-insensitive search in Postgres
    term_clause = "(" + " OR ".join(f"{f} ILIKE %s" for f in fields) + ")"
    joiner = " AND " if mode == "and" else " OR "
    where = joiner.join(term_clause for _ in terms)
    params = [t.replace("*", "%") if "*" in t else f"%{t}%"
              for t in terms for _ in fields]
    sql = f"SELECT * FROM po_detail WHERE {where} ORDER BY order_date DESC LIMIT 500"
    rows = conn.execute(sql, params).fetchall()
    return rows


@app.get("/summary/{part_num}")
def get_part_summary(part_num: str, conn=Depends(get_conn)):
    row = conn.execute(
        """
        SELECT part_num,
               COUNT(*)                                          AS total_orders,
               MAX(order_date)                                   AS last_order_date,
               ROUND(AVG(unit_cost)::NUMERIC, 4)                AS avg_unit_cost,
               MIN(unit_cost)                                    AS min_unit_cost,
               MAX(unit_cost)                                    AS max_unit_cost,
               (SELECT unit_cost FROM po_detail
                WHERE part_num = p.part_num
                ORDER BY order_date DESC LIMIT 1)               AS last_unit_cost,
               (SELECT vendor_name FROM po_detail
                WHERE part_num = p.part_num
                ORDER BY order_date DESC LIMIT 1)               AS last_vendor
        FROM po_detail p
        WHERE part_num = %s
        GROUP BY part_num
        """,
        (part_num,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return row


@app.post("/bulk-lookup")
def bulk_lookup(body: BulkLookupRequest, conn=Depends(get_conn)):
    if not body.part_numbers:
        return []
    placeholders = ",".join("%s" for _ in body.part_numbers)
    rows = conn.execute(
        f"SELECT * FROM po_detail WHERE part_num IN ({placeholders}) "
        f"ORDER BY part_num, order_date DESC",
        body.part_numbers,
    ).fetchall()
    return rows


# ── Inventory endpoints ────────────────────────────────────────────────────────

@app.get("/inventory")
def get_all_inventory(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM bin_inventory ORDER BY part_num, warehouse_code"
    ).fetchall()
    return rows


@app.get("/inventory/search")
def search_inventory(q: str = Query(..., min_length=1), conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM bin_inventory WHERE part_num ILIKE %s OR description ILIKE %s "
        "ORDER BY part_num LIMIT 200",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    return rows


@app.get("/inventory/parts/{part_num}")
def get_inventory_by_part(part_num: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM bin_inventory WHERE part_num = %s ORDER BY warehouse_code",
        (part_num,),
    ).fetchall()
    return rows


@app.get("/inventory/warehouses")
def get_inventory_warehouses(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT DISTINCT warehouse_code, warehouse_desc FROM bin_inventory "
        "ORDER BY warehouse_code"
    ).fetchall()
    return rows


@app.get("/inventory/warehouses/{wh_code}")
def inventory_by_warehouse(wh_code: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM bin_inventory WHERE warehouse_code = %s ORDER BY part_num",
        (wh_code,),
    ).fetchall()
    return rows


# ── Script runner endpoints (disabled on Replit) ───────────────────────────────

def _require_script_runner():
    if not ENABLE_SCRIPT_RUNNER:
        raise HTTPException(
            status_code=403,
            detail="Script runner is disabled on this deployment (ENABLE_SCRIPT_RUNNER=0)",
        )


@app.get("/scripts")
def list_scripts():
    _require_script_runner()
    return {
        sid: {"path": str(path), "exists": path.exists()}
        for sid, path in SCRIPT_WHITELIST.items()
    }


@app.post("/run-script")
async def run_script(body: RunScriptRequest):
    _require_script_runner()

    script_id = body.script_id
    if script_id not in SCRIPT_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown script '{script_id}'. Available: {list(SCRIPT_WHITELIST.keys())}",
        )

    script_path = SCRIPT_WHITELIST[script_id]
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"Script not found: {script_path}")

    args = SCRIPT_ARGS.get(script_id, []) + (body.extra_args or [])
    cmd = [
        "powershell.exe",
        "-ExecutionPolicy", "Bypass",
        "-NonInteractive",
        "-File", str(script_path),
    ] + args

    started = datetime.datetime.now()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        return {"script_id": script_id, "exit_code": -1,
                "stdout": "", "stderr": "Timed out after 300s", "duration_s": 300}

    duration = (datetime.datetime.now() - started).total_seconds()
    return {
        "script_id": script_id,
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "duration_s": round(duration, 1),
        "ran_at": started.isoformat(),
    }


# ── Static UI — must be last so API routes take priority ──────────────────────

if REACT_DIST.exists():
    app.mount("/", StaticFiles(directory=str(REACT_DIST), html=True), name="static")
