import os
import asyncio
import subprocess
import datetime
import time
import re
import json
from pathlib import Path
from typing import Optional, List
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from datalake_api import create_datalake_router

# ── Configuration ──────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
ENABLE_SCRIPT_RUNNER = os.environ.get("ENABLE_SCRIPT_RUNNER", "0") == "1"
UI_DIST = Path(
    os.environ.get("UI_DIST_PATH")
    or Path(__file__).parent / "next-ui" / "out"
).resolve()

CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_JWT_KEY = os.environ.get("CLERK_JWT_KEY", "")  # optional PEM -> networkless
APP_ORIGIN = os.environ.get("APP_ORIGIN", "")        # deployment URL for azp pinning
ALLOWED_EMAIL_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "colonydisplay.com")
IS_DEPLOYMENT = bool(os.environ.get("REPLIT_DEPLOYMENT"))
PREVIEW_ADMIN_REQUESTED = os.environ.get("PREVIEW_ADMIN_MODE", "0") == "1"
PREVIEW_LIVE_DATA_REQUESTED = os.environ.get("PREVIEW_LIVE_DATA", "0") == "1"

# This identity exists only in memory for the local preview. It is never
# inserted into Clerk or Neon.
PREVIEW_ADMIN_USER = {
    "id": 0,
    "email": "preview-admin@demo.local",
    "name": "Preview Admin",
    "role": "admin",
    "active": True,
}

# Representative, fictional records for the unsigned development preview. Keep
# these in memory so a shared preview link can never expose the read model.
PREVIEW_PO_ROWS = [
    {
        "part_num": "DEMO-LED-24",
        "description": "24 in LED light bar assembly",
        "vendor_name": "Northstar Components",
        "vendor_id": "DEMO-100",
        "po_num": 48217,
        "order_date": "2026-08-20",
        "order_qty": 48,
        "supplier_uom": "EA",
        "unit_cost": 84.5,
        "line_total": 4056.0,
        "buyer_name": "Jordan Lee",
        "project_id": "DEMO-RETAIL",
        "open_order": True,
    },
    {
        "part_num": "DEMO-LED-24",
        "description": "24 in LED light bar assembly",
        "vendor_name": "Northstar Components",
        "vendor_id": "DEMO-100",
        "po_num": 47603,
        "order_date": "2026-06-14",
        "order_qty": 36,
        "supplier_uom": "EA",
        "unit_cost": 81.75,
        "line_total": 2943.0,
        "buyer_name": "Jordan Lee",
        "project_id": "DEMO-RETAIL",
        "open_order": False,
    },
    {
        "part_num": "DEMO-ACRYL-12",
        "description": "Clear acrylic panel, 12 x 18",
        "vendor_name": "Clearview Plastics",
        "vendor_id": "DEMO-204",
        "po_num": 48192,
        "order_date": "2026-08-18",
        "order_qty": 120,
        "supplier_uom": "EA",
        "unit_cost": 12.4,
        "line_total": 1488.0,
        "buyer_name": "Morgan Chen",
        "project_id": "DEMO-FIXTURES",
        "open_order": True,
    },
    {
        "part_num": "DEMO-BRKT-90",
        "description": "Powder-coated steel mounting bracket",
        "vendor_name": "Midwest Fabrication",
        "vendor_id": "DEMO-318",
        "po_num": 48074,
        "order_date": "2026-08-11",
        "order_qty": 250,
        "supplier_uom": "EA",
        "unit_cost": 4.85,
        "line_total": 1212.5,
        "buyer_name": "Morgan Chen",
        "project_id": "DEMO-FIXTURES",
        "open_order": False,
    },
]

PREVIEW_INVENTORY_ROWS = [
    {
        "part_num": "DEMO-ACRYL-12",
        "description": "Clear acrylic panel, 12 x 18",
        "warehouse_code": "MAIN",
        "warehouse_desc": "Main warehouse",
        "bin_num": "A-14-03",
        "on_hand_qty": 86,
        "warehouse_on_hand": 126,
        "uom": "EA",
        "class_id": "PLASTIC",
        "last_vendor": "Clearview Plastics",
        "last_po_date": "2026-08-18",
        "last_unit_cost": 12.4,
    },
    {
        "part_num": "DEMO-ACRYL-12",
        "description": "Clear acrylic panel, 12 x 18",
        "warehouse_code": "WEST",
        "warehouse_desc": "West distribution center",
        "bin_num": "R-02-11",
        "on_hand_qty": 40,
        "warehouse_on_hand": 40,
        "uom": "EA",
        "class_id": "PLASTIC",
        "last_vendor": "Clearview Plastics",
        "last_po_date": "2026-08-18",
        "last_unit_cost": 12.4,
    },
    {
        "part_num": "DEMO-BRKT-90",
        "description": "Powder-coated steel mounting bracket",
        "warehouse_code": "MAIN",
        "warehouse_desc": "Main warehouse",
        "bin_num": "B-08-06",
        "on_hand_qty": 430,
        "warehouse_on_hand": 430,
        "uom": "EA",
        "class_id": "HARDWARE",
        "last_vendor": "Midwest Fabrication",
        "last_po_date": "2026-08-11",
        "last_unit_cost": 4.85,
    },
    {
        "part_num": "DEMO-LED-24",
        "description": "24 in LED light bar assembly",
        "warehouse_code": "MAIN",
        "warehouse_desc": "Main warehouse",
        "bin_num": "C-03-09",
        "on_hand_qty": 22,
        "warehouse_on_hand": 22,
        "uom": "EA",
        "class_id": "ELECTRICAL",
        "last_vendor": "Northstar Components",
        "last_po_date": "2026-08-20",
        "last_unit_cost": 84.5,
    },
]

PREVIEW_USERS = [
    PREVIEW_ADMIN_USER,
    {
        "id": -1,
        "email": "purchasing-demo@demo.local",
        "name": "Purchasing Demo",
        "role": "purchasing",
        "active": True,
        "created_at": "2026-07-01T09:00:00Z",
        "updated_at": "2026-08-20T14:30:00Z",
    },
    {
        "id": -2,
        "email": "warehouse-demo@demo.local",
        "name": "Warehouse Demo",
        "role": "warehouse",
        "active": True,
        "created_at": "2026-07-08T09:00:00Z",
        "updated_at": "2026-08-20T14:30:00Z",
    },
]

PREVIEW_ACCESS_HISTORY = [
    {
        "id": -1,
        "action": "user_created",
        "actor_type": "admin",
        "actor_user_id": 0,
        "actor_email": PREVIEW_ADMIN_USER["email"],
        "actor_label": PREVIEW_ADMIN_USER["email"],
        "target_user_id": -1,
        "target_email": "purchasing-demo@demo.local",
        "previous_state": None,
        "resulting_state": {"role": "purchasing", "active": True},
        "changed_at": "2026-07-01T09:00:00Z",
    },
    {
        "id": -2,
        "action": "activated",
        "actor_type": "system",
        "actor_user_id": None,
        "actor_email": None,
        "actor_label": "Emergency admin policy",
        "target_user_id": -2,
        "target_email": "warehouse-demo@demo.local",
        "previous_state": {"role": "warehouse", "active": False},
        "resulting_state": {"role": "warehouse", "active": True},
        "changed_at": "2026-08-20T14:30:00Z",
    },
]

PREVIEW_KPI_AS_OF = "2026-08-20"
PREVIEW_KPI_METRICS = [
    ("SH-01", "Units shipped", "count", 186, 3180, 172, 160),
    ("SH-02", "Shipping revenue", "USD", 28450, 486200, 27500, 26300),
    ("SH-03", "Orders shipped on time", "percent", 96.4, 95.8, 95, 94.7),
    ("RC-01", "Receipts processed", "count", 34, 482, 31, 29),
    ("RC-04", "Receiving accuracy", "percent", 99.1, 98.8, 98, 98.7),
    ("RC-05", "Average dock-to-stock", "hours", 3.2, 3.5, 4, 3.7),
    ("IV-01", "Inventory accuracy", "percent", 98.6, 98.2, 98, 98.3),
    ("IV-02", "Cycle counts completed", "count", 18, 244, 18, 16),
    ("FAB-01", "Fabrication output", "count", 142, 2450, 135, 128),
    ("FAB-04", "Fabrication first-pass yield", "percent", 97.8, 97.2, 96, 97.1),
    ("ASM-01", "Assembly output", "count", 96, 1684, 90, 86),
    ("KIT-01", "Kits completed", "count", 41, 706, 40, 37),
]


def _preview_metric(metric):
    metric_id, label, unit, daily, mtd, target, avg7 = metric
    return {
        "id": metric_id,
        "label": label,
        "unit": unit,
        "daily": daily,
        "mtd": mtd,
        "target": target,
        "avg7": avg7,
        "note": "Representative preview data",
    }


PREVIEW_KPI_SUMMARY = {
    "asOf": PREVIEW_KPI_AS_OF,
    "sections": [
        {"id": "shipping", "title": "Shipping", "metrics": [_preview_metric(metric) for metric in PREVIEW_KPI_METRICS[:3]]},
        {"id": "receiving", "title": "Receiving", "metrics": [_preview_metric(metric) for metric in PREVIEW_KPI_METRICS[3:6]]},
        {"id": "inventory", "title": "Inventory", "metrics": [_preview_metric(metric) for metric in PREVIEW_KPI_METRICS[6:8]]},
        {"id": "production", "title": "Production", "metrics": [_preview_metric(metric) for metric in PREVIEW_KPI_METRICS[8:]]},
    ],
    "publishedBy": "preview-fixture",
}


def _preview_kpi_trends():
    metrics = {}
    for index, metric in enumerate(PREVIEW_KPI_METRICS, start=1):
        metric_id, _, _, daily, mtd, _, _ = metric
        metrics[metric_id] = {
            "dailyLast30": [
                {"date": f"2026-08-{day:02d}", "value": round(daily * (0.84 + (day % 7) * 0.04), 2)}
                for day in range(1, 21)
            ],
            "monthlyTrailing12": [
                {"year": 2025 if month > 8 else 2026, "month": month, "label": datetime.date(2025 if month > 8 else 2026, month, 1).strftime("%b"), "value": round(mtd * (0.82 + (month % 5) * 0.045), 2)}
                for month in [9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8]
            ],
        }
    return {"asOf": PREVIEW_KPI_AS_OF, "metrics": metrics, "publishedBy": "preview-fixture"}


PREVIEW_KPI_TRENDS = _preview_kpi_trends()

# Emergency admins: comma-separated emails that are ALWAYS treated as active
# admins (and auto-inserted into the users table) so the owner can never be
# locked out by a bad edit in the Users page.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# ── Roles & sections ───────────────────────────────────────────────────────────
# Sections are the portal's building blocks; future Epicor features register a
# new section name here and gate their routes with require_section(...).

ROLES = ("admin", "purchasing", "warehouse", "viewer")
DEFAULT_ROLE = "viewer"

ROLE_LABELS = {
    "admin": "Admin",
    "purchasing": "Purchasing",
    "warehouse": "Warehouse",
    "viewer": "Viewer",
}

BASELINE_SECTIONS = ["search", "bom", "inventory", "operations_kpi"]

SECTION_LABELS = {
    "search": "Purchase order history",
    "bom": "Bill of materials",
    "inventory": "Inventory",
    "operations_kpi": "Operations KPI dashboards",
    "users": "Users & access",
    "datalake": "DataLake reports",
}

SECTIONS_BY_ROLE = {
    # Role-specific restrictions for the core dashboards are intentionally
    # deferred. Every active company user receives the same baseline access;
    # only administration and DataLake reporting are privileged today.
    "admin":      [*BASELINE_SECTIONS, "users", "datalake"],
    "purchasing": [*BASELINE_SECTIONS],
    "warehouse":  [*BASELINE_SECTIONS],
    "viewer":     [*BASELINE_SECTIONS],
}


def _section_access_descriptor(section: str) -> dict:
    return {
        "id": section,
        "label": SECTION_LABELS.get(
            section,
            section.replace("_", " ").strip().title(),
        ),
    }


def _role_access_catalog() -> dict:
    """Describe role access directly from the authorization mapping."""
    baseline = set(BASELINE_SECTIONS)
    return {
        "defaultRole": DEFAULT_ROLE,
        "baselineSections": [
            _section_access_descriptor(section)
            for section in BASELINE_SECTIONS
        ],
        "roles": [
            {
                "id": role,
                "label": ROLE_LABELS.get(role, role.replace("_", " ").title()),
                "sections": [
                    _section_access_descriptor(section)
                    for section in SECTIONS_BY_ROLE.get(role, [])
                ],
                "adminOnlySections": [
                    _section_access_descriptor(section)
                    for section in SECTIONS_BY_ROLE.get(role, [])
                    if section not in baseline
                ],
            }
            for role in ROLES
        ],
    }

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
            # Long-running VM deployments can retain a connection after Neon
            # closes it while idle. Validate on checkout so the pool replaces
            # stale connections before a request such as /me uses them.
            check=ConnectionPool.check_connection,
            min_size=1,
            max_size=10,
            open=True,
        )
    return pool


def get_conn(request: Request):
    """Dependency / helper — yields a connection from the pool."""
    # Route dependencies resolve before their handlers. Avoid creating even a
    # read-only pool connection for fixture-backed unsigned preview.
    if _preview_fixture_request(request):
        yield None
        return
    p = get_pool()
    with p.connection() as conn:
        if _preview_live_request(request):
            # The unsigned live preview is intentionally incapable of changing
            # repository state, independently of route-level mutation guards.
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                yield conn
            return
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


class CreateUserRequest(BaseModel):
    email: str
    name: Optional[str] = ""
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    name: Optional[str] = None


# ── Clerk authentication ───────────────────────────────────────────────────────

_clerk = Clerk(bearer_auth=CLERK_SECRET_KEY) if CLERK_SECRET_KEY else None
_clerk_user_cache: dict = {}  # user_id -> ({"email","name","allowed"}, fetched_at)
_CLERK_USER_TTL = 300  # seconds — bounds how long a domain-removed user stays valid


def _authorized_parties() -> Optional[List[str]]:
    # Pin azp to the deployment URL in production (per CLERK_M365_AUTH_PLAN.md).
    # Unset in dev — the SDK fails closed on tokens without an azp claim.
    if APP_ORIGIN:
        return [APP_ORIGIN.rstrip("/")]
    return None


def _preview_admin_enabled(request: Request) -> bool:
    """Allow the unsigned admin preview only on explicitly enabled dev hosts.

    REPLIT_DEPLOYMENT is the hard stop: even if PREVIEW_ADMIN_MODE is
    accidentally present in production, this path remains disabled.
    """
    if not PREVIEW_ADMIN_REQUESTED or IS_DEPLOYMENT:
        return False
    hostname = (request.url.hostname or "").lower()
    allowed_hosts = {"localhost", "127.0.0.1", "testserver"}
    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip().lower()
    if dev_domain:
        allowed_hosts.add(dev_domain)
    return hostname in allowed_hosts


def _preview_live_data_enabled(request: Request) -> bool:
    """Server-trusted opt-in for live reads by the unsigned preview identity."""
    return PREVIEW_LIVE_DATA_REQUESTED and _preview_admin_enabled(request)


def _preview_live_request(request: Request) -> bool:
    """Trusted live-preview capability plus authenticated preview request state."""
    return (
        getattr(request.state, "preview_admin", False)
        and _preview_live_data_enabled(request)
    )

def _clerk_user_info(user_id: str) -> dict:
    """Fetch (with caching) the Clerk user's email, name, and domain check."""
    cached = _clerk_user_cache.get(user_id)
    if cached and time.monotonic() - cached[1] < _CLERK_USER_TTL:
        return cached[0]
    email = None
    name = ""
    allowed = not ALLOWED_EMAIL_DOMAIN
    try:
        user = _clerk.users.get(user_id=user_id)
        emails = [e.email_address for e in (user.email_addresses or []) if e.email_address]
        name = " ".join(p for p in [user.first_name, user.last_name] if p) or ""
        suffix = "@" + ALLOWED_EMAIL_DOMAIN.lower() if ALLOWED_EMAIL_DOMAIN else ""
        domain_emails = [e for e in emails if e.lower().endswith(suffix)] if suffix else emails
        if ALLOWED_EMAIL_DOMAIN:
            allowed = bool(domain_emails)
        # Prefer the org-domain address as the canonical identity.
        email = (domain_emails or emails or [None])[0]
        if email:
            email = email.lower()
    except Exception:
        # Fail closed: cannot confirm the account belongs to the org
        allowed = False
    info = {"email": email, "name": name, "allowed": allowed}
    _clerk_user_cache[user_id] = (info, time.monotonic())
    return info


# ── App users (roles & access) ────────────────────────────────────────────────

# The users table + grants are provisioned out-of-band (see neon-schema.sql);
# the app's DB role is least-privilege (SELECT/INSERT/UPDATE only, no DDL).

_app_user_cache: dict = {}  # email -> (row dict | None, fetched_at)
_APP_USER_TTL = 30  # seconds

# Advisory lock key serializing admin-membership mutations (bootstrap,
# demote/deactivate) so races can't create zero or duplicate admins.
_USERS_ADMIN_LOCK = 774201


def _invalidate_user_cache(email: Optional[str] = None):
    if email:
        _app_user_cache.pop(email.lower(), None)
    else:
        _app_user_cache.clear()


def _get_app_user(email: str, name: str = "") -> Optional[dict]:
    """Look up the app user row by email (cached). Handles bootstrap:
    - Emergency admins (ADMIN_EMAILS) are always active admins.
    - If the table is empty, the first signer-in becomes the admin.
    - Later company-domain signers are provisioned as active viewers."""
    email = email.lower()
    cached = _app_user_cache.get(email)
    if cached and time.monotonic() - cached[1] < _APP_USER_TTL:
        return cached[0]

    p = get_pool()
    with p.connection() as conn:
        row = conn.execute(
            "SELECT * FROM po_history.users WHERE lower(email) = %s", (email,)
        ).fetchone()

        if email in ADMIN_EMAILS and (row is None or row["role"] != "admin" or not row["active"]):
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_USERS_ADMIN_LOCK,))
            row = conn.execute(
                "SELECT * FROM po_history.users WHERE lower(email) = %s", (email,)
            ).fetchone()
            if row is None or row["role"] != "admin" or not row["active"]:
                previous = row
                row = conn.execute(
                    """
                    INSERT INTO po_history.users (email, name, role, active)
                    VALUES (%s, %s, 'admin', TRUE)
                    ON CONFLICT (email) DO UPDATE
                        SET role = 'admin', active = TRUE, updated_at = now()
                    RETURNING *
                    """,
                    (email, name),
                ).fetchone()
                _record_user_access_change(
                    conn,
                    action=(
                        "user_created"
                        if previous is None
                        else _access_change_action(previous, row)
                    ),
                    actor_label="Emergency admin policy",
                    target=row,
                    previous_state=(
                        _access_state(previous) if previous is not None else None
                    ),
                )
            conn.commit()
        elif row is None:
            # Serialize just-in-time provisioning. Re-read after taking the
            # lock so concurrent requests for the same new user cannot race.
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_USERS_ADMIN_LOCK,))
            row = conn.execute(
                "SELECT * FROM po_history.users WHERE lower(email) = %s", (email,)
            ).fetchone()
            if row is None:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM po_history.users"
                ).fetchone()["n"]
                role = "admin" if count == 0 else "viewer"
                row = conn.execute(
                    "INSERT INTO po_history.users (email, name, role, active) "
                    "VALUES (%s, %s, %s, TRUE) RETURNING *",
                    (email, name, role),
                ).fetchone()
                _record_user_access_change(
                    conn,
                    action="user_created",
                    actor_label=(
                        "Portal bootstrap"
                        if role == "admin"
                        else "Automatic sign-in provisioning"
                    ),
                    target=row,
                    previous_state=None,
                )
            conn.commit()

    _app_user_cache[email] = (row, time.monotonic())
    return row

def require_auth(request: Request):
    # A real Clerk session always wins over preview mode. The fixture identity
    # is only for requests that do not present an authorization token.
    if _preview_admin_enabled(request) and not request.headers.get("authorization", "").strip():
        request.state.preview_admin = True
        request.state.real_clerk_session = False
        request.state.user_email = PREVIEW_ADMIN_USER["email"]
        request.state.user_name = PREVIEW_ADMIN_USER["name"]
        return {"preview_admin": True}

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
    info = _clerk_user_info(user_id) if user_id else {"allowed": False}
    if not user_id or not info["allowed"] or not info["email"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access restricted to {ALLOWED_EMAIL_DOMAIN} accounts",
        )
    request.state.preview_admin = False
    # This evidence is set only after Clerk has authenticated the token and the
    # existing organization-domain check has succeeded.
    request.state.real_clerk_session = True
    request.state.user_email = info["email"]
    request.state.user_name = info["name"]
    return state


def require_member(request: Request, state=Depends(require_auth)) -> dict:
    """Auth + membership: the signed-in user must be an active row in the
    users table. Returns the user row; role lands in request.state.role."""
    if getattr(request.state, "preview_admin", False):
        request.state.role = "admin"
        return PREVIEW_ADMIN_USER.copy()

    email = request.state.user_email
    row = _get_app_user(email, request.state.user_name)
    if row is None or not row["active"]:
        raise HTTPException(status_code=403, detail="no_access")
    request.state.role = row["role"]
    return row


def require_section(*sections: str):
    """Dependency factory: member's role must grant at least one of the
    given sections. All data routes are gated this way — the UI hiding a
    tab is never the security boundary."""
    def dep(row: dict = Depends(require_member)):
        allowed = SECTIONS_BY_ROLE.get(row["role"], [])
        if not set(sections) & set(allowed):
            raise HTTPException(status_code=403, detail="section_forbidden")
        return row
    return dep


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Colony Epicor Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174",
                   "http://localhost:8000", "http://localhost:8067"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# All data endpoints require a Clerk session AND membership with a role that
# grants the relevant section; /health and static stay public.
po_routes = APIRouter(dependencies=[Depends(require_section("search", "bom"))])
inv_routes = APIRouter(dependencies=[Depends(require_section("inventory"))])
admin_routes = APIRouter(dependencies=[Depends(require_section("users"))])
kpi_routes = APIRouter(
    prefix="/api/kpis",
    tags=["operations-kpi"],
    dependencies=[Depends(require_section("operations_kpi"))],
)
datalake_routes = create_datalake_router(
    require_section,
    trusted_preview_session=_preview_live_request,
)


@app.middleware("http")
async def sensitive_data_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/api/ui-version":
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif (
        request.url.path.startswith("/api/datalake")
        or request.url.path == "/api/health"
        or request.url.path == "/api/kpis"
        or request.url.path.startswith("/api/kpis/")
        # Preview HTML must be revalidated after each frontend build. Without
        # this, an already-open Replit preview can keep an old dashboard bundle
        # that does not contain newly enabled cards such as DataLake.
        or (
            _preview_admin_enabled(request)
            and not request.url.path.startswith("/_next/static/")
            and (
                request.url.path in (
                    "/",
                    "/admin",
                    "/admin/",
                    "/datalake",
                    "/datalake/",
                )
                or request.url.path.endswith(".html")
            )
        )
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


# ── Published Operations KPI read model ───────────────────────────────────────
# This intentionally uses only the approved, successful-publish views.  It is
# kept separate from PO History queries so the published-data contract never
# falls back to a live Epicor source.

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")
_METRIC_ID = re.compile(r"^[A-Z0-9-]{2,32}$")
_KPI_ERROR_UNAVAILABLE = "Published KPI data is temporarily unavailable"


class KpiRequestError(Exception):
    def __init__(self, status_code: int, error: str, details: str):
        self.status_code = status_code
        self.error = error
        self.details = details


@app.exception_handler(KpiRequestError)
async def kpi_request_error_handler(_: Request, exc: KpiRequestError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "details": exc.details},
    )


def _validate_kpi_date(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    error = "Invalid asOf date" if field == "asOf" else "Invalid date"
    if not _ISO_DATE.fullmatch(value):
        raise KpiRequestError(400, error, f"Use ?{field}=YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise KpiRequestError(400, error, f"Use ?{field}=YYYY-MM-DD")
    return value


def _validate_kpi_month(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not _ISO_MONTH.fullmatch(value):
        raise KpiRequestError(400, "Invalid month", "Use ?month=YYYY-MM")
    try:
        year, month = (int(part) for part in value.split("-"))
        datetime.date(year, month, 1)
    except ValueError:
        raise KpiRequestError(400, "Invalid month", "Use ?month=YYYY-MM")
    return value


def _kpi_read(query: str, params: tuple = ()):
    """Run one published-KPI query in a transaction-scoped read-only session."""
    try:
        with get_pool().connection(timeout=10) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL statement_timeout = '15s'")
                return conn.execute(query, params).fetchone()
    except HTTPException:
        raise
    except Exception:
        # Do not surface database topology, query text, or driver errors.
        raise KpiRequestError(503, _KPI_ERROR_UNAVAILABLE, "Please retry shortly")


def _published_payload(kind: str, as_of: Optional[str]):
    if as_of:
        row = _kpi_read(
            """
            SELECT payload FROM kpi.v_api_payload
            WHERE kind = %s AND as_of_date = %s
            ORDER BY run_id DESC LIMIT 1
            """,
            (kind, as_of),
        )
    else:
        row = _kpi_read(
            """
            SELECT payload FROM kpi.v_api_payload
            WHERE kind = %s
            ORDER BY as_of_date DESC, run_id DESC LIMIT 1
            """,
            (kind,),
        )
    if row is None:
        raise KpiRequestError(404, "Published KPI data was not found", "This business date has not been published yet")
    return row["payload"]


def _prior_weekday_central() -> datetime.date:
    today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    day = today - datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day


def _preview_request(request: Request) -> bool:
    """Whether this request is using the synthetic preview identity."""
    if hasattr(request.state, "preview_admin"):
        return request.state.preview_admin
    return _preview_admin_enabled(request)


def _preview_fixture_request(request: Request) -> bool:
    """Whether a preview read must use synthetic fixtures rather than a repo."""
    return _preview_request(request) and not _preview_live_data_enabled(request)


def _resolve_public_preview_source(request: Request):
    """Resolve fixture vs. repository for public read-model health endpoints.

    A valid presented session may use the normal development repository. An
    An absent session uses the configured preview source. Invalid presented
    credentials are never allowed to fall back to the unsigned identity.
    """
    if not _preview_admin_enabled(request):
        return
    if not request.headers.get("authorization", "").strip():
        request.state.preview_admin = True
        return
    require_auth(request)


def _preview_kpi_payload(kind: str, as_of: Optional[str]):
    if as_of and as_of != PREVIEW_KPI_AS_OF:
        raise KpiRequestError(404, "Published KPI data was not found", "This business date has not been published yet")
    return PREVIEW_KPI_SUMMARY if kind == "kpis" else PREVIEW_KPI_TRENDS


def _preview_kpi_detail(metric_id: str, period_type: str, period: str):
    if period != (PREVIEW_KPI_AS_OF if period_type == "date" else PREVIEW_KPI_AS_OF[:7]):
        raise KpiRequestError(404, "Published KPI detail was not found", "This period has not been published yet")
    metric = next((item for item in PREVIEW_KPI_METRICS if item[0] == metric_id), None)
    if metric is None:
        raise KpiRequestError(404, "Published KPI detail was not found", "This period has not been published yet")
    _, label, unit, daily, mtd, _, _ = metric
    if period_type == "date":
        rows = [
            {"work_center": "Assembly", "measure": label, "reference": "DEMO-1001", "quantity": round(daily * 0.56, 2), "status": "Complete"},
            {"work_center": "Fabrication", "measure": label, "reference": "DEMO-1002", "quantity": round(daily * 0.44, 2), "status": "Complete"},
        ]
        total = daily
    else:
        rows = [
            {"month": period, "work_center": "Assembly", "measure": label, "quantity": round(mtd * 0.54, 2)},
            {"month": period, "work_center": "Fabrication", "measure": label, "quantity": round(mtd * 0.46, 2)},
        ]
        total = mtd
    return {
        "metricId": metric_id,
        "periodType": period_type,
        "period": period,
        "rowCount": len(rows),
        "totals": {unit: total},
        "rows": rows,
        "publishedBy": "preview-fixture",
    }


@kpi_routes.get("")
def get_kpis(request: Request, asOf: Optional[str] = None):
    as_of = _validate_kpi_date(asOf, "asOf")
    if _preview_fixture_request(request):
        return _preview_kpi_payload("kpis", as_of)
    return _published_payload("kpis", as_of)


@kpi_routes.get("/trends")
def get_kpi_trends(request: Request, asOf: Optional[str] = None):
    as_of = _validate_kpi_date(asOf, "asOf")
    if _preview_fixture_request(request):
        return _preview_kpi_payload("trends", as_of)
    return _published_payload("trends", as_of)


@kpi_routes.get("/{metric_id}/detail")
def get_kpi_detail(request: Request, metric_id: str, date: Optional[str] = None, month: Optional[str] = None):
    if not _METRIC_ID.fullmatch(metric_id):
        raise KpiRequestError(400, "Invalid metric ID", "Use a published metric ID")
    date = _validate_kpi_date(date, "date")
    month = _validate_kpi_month(month)
    if bool(date) == bool(month):
        raise KpiRequestError(
            400,
            "Choose one published period",
            "Provide exactly one of ?date=YYYY-MM-DD or ?month=YYYY-MM",
        )
    period_type, period = ("date", date) if date else ("month", month)
    if _preview_fixture_request(request):
        return _preview_kpi_detail(metric_id, period_type, period)
    row = _kpi_read(
        """
        SELECT payload FROM kpi.v_detail_payload
        WHERE metric_id = %s AND period_type = %s AND period = %s
        ORDER BY run_id DESC LIMIT 1
        """,
        (metric_id, period_type, period),
    )
    if row is None:
        raise KpiRequestError(404, "Published KPI detail was not found", "This period has not been published yet")
    return row["payload"]


@app.get("/api/health", tags=["operations-kpi"])
def kpi_health(request: Request):
    """Public, sanitized freshness for monitoring and the KPI dashboard."""
    _resolve_public_preview_source(request)
    if _preview_fixture_request(request):
        return {
            "status": "ok",
            "state": "ok",
            "database": "sample",
            "databaseStatus": "sample",
            "appVersion": "preview-fixture",
            "latestSuccessfulPublish": PREVIEW_KPI_AS_OF,
            "lastSuccessAt": "2026-08-20T14:30:00+00:00",
            "expectedBusinessDate": PREVIEW_KPI_AS_OF,
            "failures7d": 0,
        }
    try:
        row = _kpi_read(
            "SELECT latest_as_of, last_success_at, failures_7d FROM kpi.v_publish_status"
        )
        latest = row["latest_as_of"] if row else None
        expected = _prior_weekday_central()
        state = "ok" if latest and latest >= expected else "stale"
        return {
            "status": "ok",
            "state": state,
            "database": "neon",
            "databaseStatus": "connected",
            "appVersion": os.environ.get("APP_VERSION", "unknown"),
            "latestSuccessfulPublish": str(latest) if latest else None,
            "lastSuccessAt": row["last_success_at"].isoformat() if row and row["last_success_at"] else None,
            "expectedBusinessDate": str(expected),
            "failures7d": int(row["failures_7d"] or 0) if row else 0,
        }
    except KpiRequestError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "state": "error",
                "database": "neon",
                "databaseStatus": "unavailable",
                "appVersion": os.environ.get("APP_VERSION", "unknown"),
                "latestSuccessfulPublish": None,
                "lastSuccessAt": None,
                "expectedBusinessDate": str(_prior_weekday_central()),
                "failures7d": 0,
            },
        )


# ── Clerk Frontend API proxy (production only) ────────────────────────────────
# Proxies Clerk FAPI through this domain so auth works on the deployment URL.
# Inactive in development — the Clerk dev instance is reached directly.

CLERK_FAPI = "https://frontend-api.clerk.dev"
CLERK_PROXY_PATH = "/api/__clerk"
_HOP_BY_HOP = {"transfer-encoding", "connection", "keep-alive", "host",
               "content-length", "content-encoding", "te", "trailer",
               "upgrade", "proxy-authenticate", "proxy-authorization"}
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

    # Prefer the configured canonical origin; fall back to platform-set
    # forwarded headers (Replit's edge injects these) only when unset.
    if APP_ORIGIN:
        proxy_origin = APP_ORIGIN.rstrip("/")
    else:
        proto = request.headers.get("x-forwarded-proto", "https")
        fwd_host = request.headers.get("x-forwarded-host", "")
        host = fwd_host.split(",")[0].strip() or request.headers.get("host", "")
        proxy_origin = f"{proto}://{host}"

    # Drop hop-by-hop headers plus any header nominated by Connection.
    connection_tokens = {t.strip().lower()
                         for t in request.headers.get("connection", "").split(",") if t.strip()}
    drop = _DROP_REQUEST_HEADERS | connection_tokens
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in drop}
    headers["Clerk-Proxy-Url"] = f"{proxy_origin}{CLERK_PROXY_PATH}"
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

    # Preserve duplicate headers (critical: Clerk sets multiple Set-Cookie
    # headers during sign-in; collapsing them into a dict drops cookies and
    # breaks the OAuth callback with "authorization_invalid").
    resp = Response(content=upstream.content, status_code=upstream.status_code)
    if "content-type" in resp.headers:
        del resp.headers["content-type"]
    for k, v in upstream.headers.multi_items():
        if k.lower() in _HOP_BY_HOP:
            continue
        resp.headers.append(k, v)
    return resp


# ── PO history endpoints ───────────────────────────────────────────────────────

def _preview_rows_for_part(part_num: str):
    return [row.copy() for row in PREVIEW_PO_ROWS if row["part_num"].lower() == part_num.lower()]


def _preview_search_rows(terms: List[str], mode: str):
    def matches(row: dict, term: str):
        needle = term.lower()
        pattern = re.escape(needle).replace(r"\*", ".*")
        return any(re.search(pattern, str(row.get(field, "")).lower()) for field in ("part_num", "vendor_name", "description"))

    return [
        row.copy() for row in PREVIEW_PO_ROWS
        if (all(matches(row, term) for term in terms) if mode == "and" else any(matches(row, term) for term in terms))
    ]


def _preview_part_summary(part_num: str):
    rows = _preview_rows_for_part(part_num)
    if not rows:
        raise HTTPException(status_code=404, detail="Part not found")
    costs = [float(row["unit_cost"]) for row in rows]
    quantities = [float(row["order_qty"]) for row in rows]
    latest = max(rows, key=lambda row: row["order_date"])
    return {
        "part_num": latest["part_num"],
        "total_orders": len(rows),
        "last_order_date": latest["order_date"],
        "avg_unit_cost": round(sum(costs) / len(costs), 4),
        "min_unit_cost": min(costs),
        "max_unit_cost": max(costs),
        "last_unit_cost": latest["unit_cost"],
        "last_vendor": latest["vendor_name"],
        "std_mtl_cost": latest["unit_cost"],
        "avg_mtl_cost": round(sum(costs) / len(costs), 4),
        "total_qty": round(sum(quantities), 4),
    }


@po_routes.get("/recent")
def get_recent(request: Request, limit: int = 50, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return [row.copy() for row in PREVIEW_PO_ROWS[:max(0, limit)]]
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
def health(request: Request):
    _resolve_public_preview_source(request)
    if _preview_fixture_request(request):
        return {
            "status": "ok",
            "rows": len(PREVIEW_PO_ROWS),
            "max_order_date": PREVIEW_PO_ROWS[0]["order_date"],
            "data_age_days": 0,
        }
    with get_pool().connection() as conn:
        if _preview_live_request(request):
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                row = conn.execute(
                    "SELECT COUNT(*) AS rows, MAX(order_date) AS max_order_date FROM po_history.po_detail"
                ).fetchone()
        else:
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


@po_routes.get("/parts/{part_num}")
def get_part_history(part_num: str, request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return _preview_rows_for_part(part_num)
    rows = conn.execute(
        "SELECT * FROM po_history.po_detail WHERE part_num = %s ORDER BY order_date DESC",
        (part_num,),
    ).fetchall()
    return rows


@po_routes.get("/vendors/{vendor_id}")
def get_vendor_history(vendor_id: str, request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return [row.copy() for row in PREVIEW_PO_ROWS if row["vendor_id"].lower() == vendor_id.lower()]
    rows = conn.execute(
        "SELECT * FROM po_history.po_detail WHERE vendor_id = %s ORDER BY order_date DESC",
        (vendor_id,),
    ).fetchall()
    return rows


@po_routes.get("/search")
def search(request: Request, q: str = Query(..., min_length=1), mode: str = Query("or"),
           conn=Depends(get_conn)):
    terms = [t.strip() for t in q.split(",") if t.strip()]
    if not terms:
        raise HTTPException(status_code=400, detail="No search terms provided")
    if _preview_fixture_request(request):
        return _preview_search_rows(terms, mode)
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


@po_routes.get("/summary/{part_num}")
def get_part_summary(part_num: str, request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return _preview_part_summary(part_num)
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


@po_routes.post("/bulk-lookup")
def bulk_lookup(body: BulkLookupRequest, request: Request, conn=Depends(get_conn)):
    if not body.part_numbers:
        return []
    if len(body.part_numbers) > 500:
        raise HTTPException(status_code=400, detail="Too many part numbers (max 500)")
    if _preview_fixture_request(request):
        requested = {part_num.lower() for part_num in body.part_numbers}
        return [
            row.copy() for row in sorted(PREVIEW_PO_ROWS, key=lambda row: (row["part_num"], row["order_date"]), reverse=True)
            if row["part_num"].lower() in requested
        ]
    placeholders = ",".join("%s" for _ in body.part_numbers)
    rows = conn.execute(
        f"SELECT * FROM po_history.po_detail WHERE part_num IN ({placeholders}) "
        f"ORDER BY part_num, order_date DESC",
        body.part_numbers,
    ).fetchall()
    return rows


# ── Inventory endpoints ────────────────────────────────────────────────────────

@inv_routes.get("/inventory")
def get_all_inventory(request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return [row.copy() for row in PREVIEW_INVENTORY_ROWS]
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory ORDER BY part_num, warehouse_code"
    ).fetchall()
    return rows


@inv_routes.get("/inventory/search")
def search_inventory(request: Request, q: str = Query(..., min_length=1), conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        needle = q.lower()
        return [
            row.copy() for row in PREVIEW_INVENTORY_ROWS
            if needle in row["part_num"].lower() or needle in row["description"].lower()
        ]
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory WHERE part_num ILIKE %s OR description ILIKE %s "
        "ORDER BY part_num LIMIT 200",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    return rows


@inv_routes.get("/inventory/parts/{part_num}")
def get_inventory_by_part(part_num: str, request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return [
            row.copy() for row in PREVIEW_INVENTORY_ROWS
            if row["part_num"].lower() == part_num.lower()
        ]
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory WHERE part_num = %s ORDER BY warehouse_code",
        (part_num,),
    ).fetchall()
    return rows


@inv_routes.get("/inventory/warehouses")
def get_inventory_warehouses(request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        warehouses = {
            (row["warehouse_code"], row["warehouse_desc"])
            for row in PREVIEW_INVENTORY_ROWS
        }
        return [
            {"warehouse_code": code, "warehouse_desc": desc}
            for code, desc in sorted(warehouses)
        ]
    rows = conn.execute(
        "SELECT DISTINCT warehouse_code, warehouse_desc FROM po_history.bin_inventory "
        "ORDER BY warehouse_code"
    ).fetchall()
    return rows


@inv_routes.get("/inventory/warehouses/{wh_code}")
def inventory_by_warehouse(wh_code: str, request: Request, conn=Depends(get_conn)):
    if _preview_fixture_request(request):
        return [
            row.copy() for row in PREVIEW_INVENTORY_ROWS
            if row["warehouse_code"].lower() == wh_code.lower()
        ]
    rows = conn.execute(
        "SELECT * FROM po_history.bin_inventory WHERE warehouse_code = %s ORDER BY part_num",
        (wh_code,),
    ).fetchall()
    return rows


# ── Current user & user management ────────────────────────────────────────────

@app.get("/api/preview-mode")
def preview_mode(request: Request):
    """Public runtime flag used before Clerk mounts in the browser."""
    enabled = _preview_admin_enabled(request)
    return {
        "enabled": enabled,
        "liveData": enabled and _preview_live_data_enabled(request),
    }


@app.get("/api/ui-version")
def ui_version():
    """Return the frontend export identifier without allowing cached responses."""
    version_file = UI_DIST / "ui-version.json"
    if not version_file.is_file():
        raise HTTPException(status_code=503, detail="Frontend build version is unavailable")
    try:
        payload = json.loads(version_file.read_text(encoding="utf-8"))
        build_id = payload["buildId"]
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("buildId must be a non-empty string")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Frontend build version is invalid") from exc

    return JSONResponse(
        {"buildId": build_id},
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/me")
def me(request: Request, state=Depends(require_auth)):
    """Who am I? Requires sign-in + org domain, but NOT membership — this is
    how the frontend learns whether to show the app or the no-access screen."""
    if getattr(request.state, "preview_admin", False):
        live_data = _preview_live_data_enabled(request)
        return {
            "access": True,
            "email": PREVIEW_ADMIN_USER["email"],
            "name": PREVIEW_ADMIN_USER["name"],
            "role": PREVIEW_ADMIN_USER["role"],
            "sections": [
                section for section in SECTIONS_BY_ROLE["admin"]
                if live_data or section != "datalake"
            ],
            "previewMode": True,
            "liveData": live_data,
        }

    email = request.state.user_email
    row = _get_app_user(email, request.state.user_name)
    if row is None or not row["active"]:
        return {"access": False, "email": email}
    return {
        "access": True,
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "sections": SECTIONS_BY_ROLE.get(row["role"], []),
        "previewMode": False,
        "liveData": False,
    }


def _validate_role(role: str):
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Valid: {list(ROLES)}")

def _access_state(user: dict) -> dict:
    return {
        "role": user["role"],
        "active": bool(user["active"]),
    }


def _access_change_action(previous: dict, resulting: dict) -> Optional[str]:
    role_changed = resulting["role"] != previous["role"]
    active_changed = bool(resulting["active"]) != bool(previous["active"])
    if role_changed and active_changed:
        return "access_changed"
    if role_changed:
        return "role_changed"
    if active_changed:
        return "activated" if resulting["active"] else "deactivated"
    return None


def _record_user_access_change(
    conn,
    *,
    action: str,
    target: dict,
    previous_state: Optional[dict],
    actor_email: Optional[str] = None,
    actor_label: Optional[str] = None,
):
    normalized_actor_email = actor_email.lower() if actor_email else None
    actor_type = "admin" if normalized_actor_email else "system"
    actor_label = actor_label or normalized_actor_email
    if not actor_label:
        raise ValueError("Access audit actor label is required")
    conn.execute(
        """
        INSERT INTO po_history.user_access_audit (
            action,
            actor_type,
            actor_user_id,
            actor_email,
            actor_label,
            target_user_id,
            target_email,
            previous_state,
            resulting_state
        )
        VALUES (
            %s,
            %s,
            (SELECT id FROM po_history.users WHERE lower(email) = %s),
            %s,
            %s,
            %s,
            %s,
            %s::jsonb,
            %s::jsonb
        )
        """,
        (
            action,
            actor_type,
            normalized_actor_email,
            normalized_actor_email,
            actor_label,
            target["id"],
            target["email"],
            json.dumps(previous_state) if previous_state is not None else None,
            json.dumps(_access_state(target)),
        ),
    )


@admin_routes.get("/roles")
def list_roles():
    return _role_access_catalog()


@admin_routes.get("/users/access-history")
def list_user_access_history(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    conn=Depends(get_conn),
):
    if getattr(request.state, "preview_admin", False):
        return [entry.copy() for entry in PREVIEW_ACCESS_HISTORY[:limit]]
    return conn.execute(
        """
        SELECT
            id,
            action,
            actor_type,
            actor_user_id,
            actor_email,
            actor_label,
            target_user_id,
            target_email,
            previous_state,
            resulting_state,
            changed_at
        FROM po_history.user_access_audit
        ORDER BY changed_at DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()


@admin_routes.get("/users")
def list_users(request: Request, conn=Depends(get_conn)):
    if getattr(request.state, "preview_admin", False):
        return [user.copy() for user in PREVIEW_USERS]
    return conn.execute(
        "SELECT id, email, name, role, active, created_at, updated_at "
        "FROM po_history.users ORDER BY email"
    ).fetchall()


@admin_routes.post("/users")
def create_user(body: CreateUserRequest, request: Request, conn=Depends(get_conn)):
    if getattr(request.state, "preview_admin", False):
        raise HTTPException(status_code=403, detail="User changes are disabled in preview mode")
    email = body.email.strip().lower()
    if ALLOWED_EMAIL_DOMAIN and not email.endswith("@" + ALLOWED_EMAIL_DOMAIN.lower()):
        raise HTTPException(
            status_code=400,
            detail=f"Email must be a @{ALLOWED_EMAIL_DOMAIN} address",
        )
    _validate_role(body.role)
    existing = conn.execute(
        "SELECT id FROM po_history.users WHERE lower(email) = %s", (email,)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")
    row = conn.execute(
        "INSERT INTO po_history.users (email, name, role) VALUES (%s, %s, %s) "
        "RETURNING id, email, name, role, active, created_at, updated_at",
        (email, (body.name or "").strip(), body.role),
    ).fetchone()
    _record_user_access_change(
        conn,
        action="user_created",
        actor_email=request.state.user_email,
        target=row,
        previous_state=None,
    )
    conn.commit()
    _invalidate_user_cache(email)
    return row


@admin_routes.patch("/users/{user_id}")
def update_user(user_id: int, body: UpdateUserRequest, request: Request,
                conn=Depends(get_conn)):
    if getattr(request.state, "preview_admin", False):
        raise HTTPException(status_code=403, detail="User changes are disabled in preview mode")
    # Serialize admin-membership mutations so two concurrent demotions
    # cannot slip past the last-admin count check.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_USERS_ADMIN_LOCK,))
    row = conn.execute(
        "SELECT * FROM po_history.users WHERE id = %s", (user_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    role = body.role if body.role is not None else row["role"]
    active = body.active if body.active is not None else row["active"]
    name = body.name if body.name is not None else row["name"]
    _validate_role(role)

    # Guard: an admin cannot demote or deactivate themselves, and the last
    # active admin can never be removed — the portal must always have one.
    is_self = row["email"].lower() == request.state.user_email
    losing_admin = row["role"] == "admin" and row["active"] and (role != "admin" or not active)
    if losing_admin:
        if is_self:
            raise HTTPException(status_code=400, detail="You cannot remove your own admin access")
        n_admins = conn.execute(
            "SELECT COUNT(*) AS n FROM po_history.users WHERE role = 'admin' AND active"
        ).fetchone()["n"]
        if n_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last active admin")

    updated = conn.execute(
        "UPDATE po_history.users SET role = %s, active = %s, name = %s, updated_at = now() "
        "WHERE id = %s RETURNING id, email, name, role, active, created_at, updated_at",
        (role, active, name, user_id),
    ).fetchone()
    action = _access_change_action(row, updated)
    if action:
        _record_user_access_change(
            conn,
            action=action,
            actor_email=request.state.user_email,
            target=updated,
            previous_state=_access_state(row),
        )
    conn.commit()
    _invalidate_user_cache(row["email"])
    return updated


# ── Script runner endpoints (disabled on Replit) ───────────────────────────────

def _require_script_runner():
    if not ENABLE_SCRIPT_RUNNER:
        raise HTTPException(
            status_code=403,
            detail="Script runner is disabled on this deployment (ENABLE_SCRIPT_RUNNER=0)",
        )


@admin_routes.get("/scripts")
def list_scripts():
    _require_script_runner()
    return {
        sid: {"path": str(path), "exists": path.exists()}
        for sid, path in SCRIPT_WHITELIST.items()
    }


@admin_routes.post("/run-script")
async def run_script(body: RunScriptRequest, request: Request):
    if getattr(request.state, "preview_admin", False):
        raise HTTPException(status_code=403, detail="Changes are disabled in preview mode")
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

app.include_router(po_routes)
app.include_router(inv_routes)
app.include_router(admin_routes)
app.include_router(kpi_routes)
app.include_router(datalake_routes)


def _page_export_file(page: str) -> Optional[Path]:
    candidates = (UI_DIST / f"{page}.html", UI_DIST / page / "index.html")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


@app.get("/datalake", include_in_schema=False)
@app.get("/datalake/", include_in_schema=False)
def datalake_page():
    export_file = _page_export_file("datalake")
    if export_file is None:
        raise HTTPException(status_code=404, detail="DataLake page is not built")
    return FileResponse(export_file)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page():
    export_file = _page_export_file("admin")
    if export_file is None:
        raise HTTPException(status_code=404, detail="Admin page is not built")
    return FileResponse(export_file)


if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="static")
