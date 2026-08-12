import os
import asyncio
import subprocess
import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# ── Configuration ──────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
ENABLE_SCRIPT_RUNNER = os.environ.get("ENABLE_SCRIPT_RUNNER", "0") == "1"
UI_DIST = Path(__file__).parent / "next-ui" / "out"

CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_JWT_KEY = os.environ.get("CLERK_JWT_KEY", "")  # optional PEM -> networkless
APP_ORIGIN = os.environ.get("APP_ORIGIN", "")        # deployment URL for azp pinning
ALLOWED_EMAIL_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "colonydisplay.com")
IS_DEPLOYMENT = bool(os.environ.get("REPLIT_DEPLOYMENT"))

# ── Connection pool ────────────────────────────────────────────────────────────
# Pool is created at startup; lazy=True lets the app start before DATABASE_URL
# is populated (e.g. during local dev without secrets).

pool: Optional[ConnectionPool] = None


def _set_search_path(conn):
    conn.execute("SET search_path TO po_history, public")
    conn.commit()


def get_pool() -> ConnectionPool:
    global pool
    if pool is None:
        if not DATABASE_URL:
            raise HTTPException(
                status_code=503,
                detail="NEON_DATABASE_URL is not configured — add it to Replit Secrets",
            )
        pool = ConnectionPool(
            DATABASE_URL,
            kwargs={
                "row_factory": dict_row,
                # Normalize: Neon requires TLS, and the app's data lives in
                # the neondb database (overridable via NEON_DATABASE).
                "sslmode": "require",
                "dbname": os.environ.get("NEON_DATABASE", "neondb"),
            },
            # Neon's pooler (PgBouncer) rejects search_path as a startup
            # option, so set it after each connection is established.
            configure=_set_search_path,
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


# ── Clerk authentication ───────────────────────────────────────────────────────

_clerk = Clerk(bearer_auth=CLERK_SECRET_KEY) if CLERK_SECRET_KEY else None
_user_domain_cache: dict = {}  # user_id -> bool (email domain allowed)


def _authorized_parties() -> Optional[List[str]]:
    # Pin azp to the deployment URL in production (per CLERK_M365_AUTH_PLAN.md).
    # Unset in dev — the SDK fails closed on tokens without an azp claim.
    if APP_ORIGIN:
        return [APP_ORIGIN.rstrip("/")]
    return None

def _email_domain_allowed(user_id: str) -> bool:
    """Check (with caching) that the Clerk user's email is on the allowed domain."""
    if not ALLOWED_EMAIL_DOMAIN:
        return True
    if user_id in _user_domain_cache:
        return _user_domain_cache[user_id]
    try:
        user = _clerk.users.get(user_id=user_id)
        emails = [e.email_address for e in (user.email_addresses or [])]
        allowed = any(
            e.lower().endswith("@" + ALLOWED_EMAIL_DOMAIN.lower()) for e in emails
        )
    except Exception:
        # Fail closed: cannot confirm the account belongs to the org
        allowed = False
    _user_domain_cache[user_id] = allowed
    return allowed

def require_auth(request: Request):
    if _clerk is None:
        raise HTTPException(status_code=503, detail="Auth is not configured")

    opts = {}
    if CLERK_JWT_KEY:
        opts["jwt_key"] = CLERK_JWT_KEY
    parties = _authorized_parties()
    if parties:
        opts["authorized_parties"] = parties

    hx_request = httpx.Request(
        method=request.method,
        url=str(request.url),
        headers=dict(request.headers),
    )
    state = _clerk.authenticate_request(hx_request, AuthenticateRequestOptions(**opts))
    if not state.is_signed_in:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = (state.payload or {}).get("sub")
    if not user_id or not _email_domain_allowed(user_id):
        raise HTTPException(
            status_code=403,
            detail=f"Access restricted to {ALLOWED_EMAIL_DOMAIN} accounts",
        )
    return state


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Colony PO History API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174",
                   "http://localhost:8000", "http://localhost:8067"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# All data endpoints require a Clerk session; /health and static stay public.
protected = APIRouter(dependencies=[Depends(require_auth)])


# ── Clerk Frontend API proxy (production only) ────────────────────────────────
# Proxies Clerk FAPI through this domain so auth works on the deployment URL.
# Inactive in development — the Clerk dev instance is reached directly.

CLERK_FAPI = "https://frontend-api.clerk.dev"
CLERK_PROXY_PATH = "/api/__clerk"
_HOP_BY_HOP = {"transfer-encoding", "connection", "keep-alive", "host",
               "content-length", "content-encoding"}
# Never forward the browser's Accept-Encoding: it may advertise codings
# (e.g. brotli) that httpx cannot decode in this environment, which would
# corrupt proxied bodies while still returning 200. Let httpx negotiate
# only encodings it can transparently decode.
_DROP_REQUEST_HEADERS = _HOP_BY_HOP | {"accept-encoding"}


@app.api_route(CLERK_PROXY_PATH + "/{path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def clerk_proxy(path: str, request: Request):
    if not IS_DEPLOYMENT or not CLERK_SECRET_KEY:
        raise HTTPException(status_code=404)

    proto = request.headers.get("x-forwarded-proto", "https")
    fwd_host = request.headers.get("x-forwarded-host", "")
    host = fwd_host.split(",")[0].strip() or request.headers.get("host", "")

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _DROP_REQUEST_HEADERS}
    headers["Clerk-Proxy-Url"] = f"{proto}://{host}{CLERK_PROXY_PATH}"
    headers["Clerk-Secret-Key"] = CLERK_SECRET_KEY
    xff = request.headers.get("x-forwarded-for", "")
    client_ip = xff.split(",")[0].strip() or (request.client.host if request.client else "")
    if client_ip:
        headers["X-Forwarded-For"] = client_ip

    url = f"{CLERK_FAPI}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    body = await request.body()

    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.request(request.method, url,
                                        headers=headers, content=body)

    resp_headers = {k: v for k, v in upstream.headers.items()
                    if k.lower() not in _HOP_BY_HOP}
    return Response(content=upstream.content, status_code=upstream.status_code,
                    headers=resp_headers)


# ── PO history endpoints ───────────────────────────────────────────────────────

@protected.get("/recent")
def get_recent(limit: int = 50, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.po_detail ORDER BY order_date DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return rows


@app.get("/v1/oauth_callback")
def oauth_callback_error():
    # Clerk redirects failed OAuth attempts here; send users back to the app
    # instead of showing a raw 404.
    return RedirectResponse(url="/", status_code=302)


@app.get("/health")
def health(conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT COUNT(*) AS rows, MAX(order_date) AS max_order_date FROM po_history.po_detail"
    ).fetchone()
    max_date = row["max_order_date"]
    age_days = (datetime.date.today() - max_date).days if max_date else None
    return {
        "status": "ok",
        "rows": row["rows"],
        "max_order_date": str(max_date) if max_date else None,
        "data_age_days": age_days,
    }


@protected.get("/parts/{part_num}")
def get_part_history(part_num: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.po_detail WHERE part_num = %s ORDER BY order_date DESC",
        (part_num,),
    ).fetchall()
    return rows


@protected.get("/vendors/{vendor_id}")
def get_vendor_history(vendor_id: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.po_detail WHERE vendor_id = %s ORDER BY order_date DESC",
        (vendor_id,),
    ).fetchall()
    return rows


@protected.get("/search")
def search(q: str = Query(..., min_length=1), mode: str = Query("or"),
           conn=Depends(get_conn)):
    terms = [t.strip() for t in q.split(",") if t.strip()]
    if not terms:
        raise HTTPException(status_code=400, detail="No search terms provided")
    fields = ["part_num", "vendor_name", "description"]
    # ILIKE for case-insensitive search in Postgres
    term_clause = "(" + " OR ".join(f"{f} ILIKE %s" for f in fields) + ")"
    joiner = " AND " if mode == "and" else " OR "
    where = joiner.join(term_clause for _ in terms)
    params = [t.replace("*", "%") if "*" in t else f"%{t}%"
              for t in terms for _ in fields]
    sql = f"SELECT * FROM po_history.po_detail WHERE {where} ORDER BY order_date DESC LIMIT 500"
    rows = conn.execute(sql, params).fetchall()
    return rows


@protected.get("/summary/{part_num}")
def get_part_summary(part_num: str, conn=Depends(get_conn)):
    row = conn.execute(
        """
        SELECT part_num,
               COUNT(*)                                          AS total_orders,
               MAX(order_date)                                   AS last_order_date,
               ROUND(AVG(unit_cost)::NUMERIC, 4)                AS avg_unit_cost,
               MIN(unit_cost)                                    AS min_unit_cost,
               MAX(unit_cost)                                    AS max_unit_cost,
               (SELECT unit_cost FROM po_history.po_detail
                WHERE part_num = p.part_num
                ORDER BY order_date DESC LIMIT 1)               AS last_unit_cost,
               (SELECT vendor_name FROM po_history.po_detail
                WHERE part_num = p.part_num
                ORDER BY order_date DESC LIMIT 1)               AS last_vendor
        FROM po_history.po_detail p
        WHERE part_num = %s
        GROUP BY part_num
        """,
        (part_num,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return row


@protected.post("/bulk-lookup")
def bulk_lookup(body: BulkLookupRequest, conn=Depends(get_conn)):
    if not body.part_numbers:
        return []
    if len(body.part_numbers) > 500:
        raise HTTPException(status_code=400, detail="Too many part numbers (max 500)")
    placeholders = ",".join("%s" for _ in body.part_numbers)
    rows = conn.execute(
        f"SELECT * FROM po_history.po_detail WHERE part_num IN ({placeholders}) "
        f"ORDER BY part_num, order_date DESC",
        body.part_numbers,
    ).fetchall()
    return rows


# ── Inventory endpoints ────────────────────────────────────────────────────────

@protected.get("/inventory")
def get_all_inventory(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory ORDER BY part_num, warehouse_code"
    ).fetchall()
    return rows


@protected.get("/inventory/search")
def search_inventory(q: str = Query(..., min_length=1), conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory WHERE part_num ILIKE %s OR description ILIKE %s "
        "ORDER BY part_num LIMIT 200",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    return rows


@protected.get("/inventory/parts/{part_num}")
def get_inventory_by_part(part_num: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory WHERE part_num = %s ORDER BY warehouse_code",
        (part_num,),
    ).fetchall()
    return rows


@protected.get("/inventory/warehouses")
def get_inventory_warehouses(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT DISTINCT warehouse_code, warehouse_desc FROM po_history.bin_inventory "
        "ORDER BY warehouse_code"
    ).fetchall()
    return rows


@protected.get("/inventory/warehouses/{wh_code}")
def inventory_by_warehouse(wh_code: str, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory WHERE warehouse_code = %s ORDER BY part_num",
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


@protected.get("/scripts")
def list_scripts():
    _require_script_runner()
    return {
        sid: {"path": str(path), "exists": path.exists()}
        for sid, path in SCRIPT_WHITELIST.items()
    }


@protected.post("/run-script")
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


# ── Register protected routes, then static UI last ────────────────────────────

app.include_router(protected)


if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="static")
