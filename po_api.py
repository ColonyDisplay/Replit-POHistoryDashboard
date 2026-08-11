import sqlite3
import subprocess
import asyncio
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import datetime

DB_PATH    = Path(__file__).parent / "Database" / "po_history.db"
INV_PATH   = Path(__file__).parent / "Database" / "bin_inventory.db"
REACT_DIST = Path(__file__).parent / "react-ui" / "dist"

# ── Script runner — whitelisted scripts Fred can invoke headlessly ─────────────
# Base dir for all Colony projects
PROJECTS_ROOT = Path(r"C:\VSCode_Projects\Colony-Projects")

SCRIPT_WHITELIST = {
    "sf-epicor-audit":       PROJECTS_ROOT / "sf-epicor_sync_audit" / "Run-SFEpicorAudit.ps1",
    "sf-epicor-audit-dry":   PROJECTS_ROOT / "sf-epicor_sync_audit" / "Run-SFEpicorAudit.ps1",
    "po-detail-sync":        Path(r"C:\VSCode_Projects\Colony-Projects\PO-History-Detail-SQLLite\Run-PODetail-Report.ps1"),
    "bin-inv-sync":          Path(r"C:\VSCode_Projects\Colony-Projects\PO-History-Detail-SQLLite\Run-BinInv-Sync.ps1"),
}

SCRIPT_ARGS = {
    "sf-epicor-audit-dry": ["--dry-run"],
}


class RunScriptRequest(BaseModel):
    script_id: str
    extra_args: Optional[List[str]] = None


class BulkLookupRequest(BaseModel):
    part_numbers: List[str]


app = FastAPI(title="Colony Internal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174",
                   "http://localhost:8000", "http://localhost:8067"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _get_conn():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503,
                            detail="Database not found — run po_detail_report.py first")
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _inv_conn():
    if not INV_PATH.exists():
        raise HTTPException(status_code=503,
                            detail="Inventory database not found — run bin_inv_sync.py first")
    conn = sqlite3.connect(str(INV_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/recent")
def get_recent(limit: int = 50):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM po_detail ORDER BY order_date DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/health")
def health():
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM po_detail").fetchone()[0]
    conn.close()
    return {"status": "ok", "rows": count}


@app.get("/parts/{part_num}")
def get_part_history(part_num: str):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM po_detail WHERE part_num = ? ORDER BY order_date DESC",
        (part_num,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/vendors/{vendor_id}")
def get_vendor_history(vendor_id: str):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM po_detail WHERE vendor_id = ? ORDER BY order_date DESC",
        (vendor_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/search")
def search(q: str = Query(..., min_length=1), mode: str = Query("or")):
    terms  = [t.strip() for t in q.split(",") if t.strip()]
    fields = ["part_num", "vendor_name", "description"]
    term_clause = "(" + " OR ".join(f"{f} LIKE ?" for f in fields) + ")"
    joiner = " AND " if mode == "and" else " OR "
    where  = joiner.join(term_clause for _ in terms)
    params = [t.replace("*", "%") if "*" in t else f"%{t}%"
              for t in terms for _ in fields]
    sql = f"SELECT * FROM po_detail WHERE {where} ORDER BY order_date DESC LIMIT 500"
    conn = _get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/summary/{part_num}")
def get_part_summary(part_num: str):
    conn = _get_conn()
    row = conn.execute("""
        SELECT part_num,
               COUNT(*)                                          AS total_orders,
               MAX(order_date)                                   AS last_order_date,
               ROUND(AVG(unit_cost), 4)                          AS avg_unit_cost,
               MIN(unit_cost)                                    AS min_unit_cost,
               MAX(unit_cost)                                    AS max_unit_cost,
               (SELECT unit_cost FROM po_detail
                WHERE part_num = p.part_num
                ORDER BY order_date DESC LIMIT 1)                AS last_unit_cost,
               (SELECT vendor_name FROM po_detail
                WHERE part_num = p.part_num
                ORDER BY order_date DESC LIMIT 1)                AS last_vendor
        FROM po_detail p
        WHERE part_num = ?
        GROUP BY part_num
    """, (part_num,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return dict(row)


@app.post("/bulk-lookup")
def bulk_lookup(body: BulkLookupRequest):
    if not body.part_numbers:
        return []
    conn = _get_conn()
    placeholders = ",".join("?" for _ in body.part_numbers)
    rows = conn.execute(
        f"SELECT * FROM po_detail WHERE part_num IN ({placeholders}) "
        f"ORDER BY part_num, order_date DESC",
        body.part_numbers
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/inventory")
def get_all_inventory():
    conn = _inv_conn()
    rows = conn.execute(
        "SELECT * FROM bin_inventory ORDER BY part_num, warehouse_code"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/inventory/search")
def search_inventory(q: str = Query(..., min_length=1)):
    conn = _inv_conn()
    rows = conn.execute(
        "SELECT * FROM bin_inventory WHERE part_num LIKE ? OR description LIKE ? "
        "ORDER BY part_num LIMIT 200",
        (f"%{q}%", f"%{q}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/inventory/parts/{part_num}")
def get_inventory_by_part(part_num: str):
    conn = _inv_conn()
    rows = conn.execute(
        "SELECT * FROM bin_inventory WHERE part_num = ? ORDER BY warehouse_code",
        (part_num,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/inventory/warehouses")
def get_inventory_warehouses():
    conn = _inv_conn()
    rows = conn.execute(
        "SELECT DISTINCT warehouse_code, warehouse_desc FROM bin_inventory "
        "ORDER BY warehouse_code"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/inventory/warehouses/{wh_code}")
def inventory_by_warehouse(wh_code: str):
    conn = _inv_conn()
    rows = conn.execute(
        "SELECT * FROM bin_inventory WHERE warehouse_code = ? ORDER BY part_num",
        (wh_code,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Script runner endpoints ────────────────────────────────────────────────────

@app.get("/scripts")
def list_scripts():
    """List all whitelisted scripts Fred can invoke."""
    return {
        sid: {"path": str(path), "exists": path.exists()}
        for sid, path in SCRIPT_WHITELIST.items()
    }


@app.post("/run-script")
async def run_script(body: RunScriptRequest):
    """
    Execute a whitelisted PowerShell script on the Windows machine.
    Returns stdout, stderr, exit_code, and duration.
    """
    script_id = body.script_id
    if script_id not in SCRIPT_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown script '{script_id}'. Available: {list(SCRIPT_WHITELIST.keys())}"
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
        "script_id":  script_id,
        "exit_code":  proc.returncode,
        "stdout":     stdout.decode(errors="replace"),
        "stderr":     stderr.decode(errors="replace"),
        "duration_s": round(duration, 1),
        "ran_at":     started.isoformat(),
    }


if REACT_DIST.exists():
    app.mount("/", StaticFiles(directory=str(REACT_DIST), html=True), name="static")
