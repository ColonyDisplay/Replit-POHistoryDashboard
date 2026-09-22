"""Privileged, read-only DataLake proxy.

Upstream routes are deliberately disabled until each lake service contract has
been reviewed.  To enable one, add a fixed ``UpstreamContract`` entry to
``APPROVED_CONTRACTS`` in source control after confirming its path, query
parameter, and response fields.  Environment variables alone never authorize
an upstream destination.
"""

import asyncio
import datetime
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse


MAX_RESPONSE_BYTES = 1_000_000
CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 20.0
TOTAL_TIMEOUT_SECONDS = 25.0
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REPORTS = ("health", "freshness", "changes", "wow", "mom", "pit")
_SERVICE_PATHS = {
    "LAKE_API_BASE_URL": "/lake-api",
    "LAKE_HEALTH_BASE_URL": "/lake-health",
}
_SAFE_PATH = re.compile(r"/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*")
_BEARER_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_TOKEN_CONFIG_MESSAGE = (
    "DataLake authentication is not configured: set a valid LAKE_API_AUTH_TOKEN in Replit Secrets"
)
APPROVED_QUERY_NAMES = frozenset({
    "shipping_as_of",
    "shipping_dod",
    "shipping_logs",
    "shipping_mom",
    "shipping_wow",
})
APPROVED_TABLES = frozenset({
    "APInvDtl", "APInvHed", "BOLDetail", "BOLHead", "COA", "COAActCat",
    "COASegValues", "COASegment", "Company", "CostGrp", "Customer",
    "DemandContractDtl", "DemandContractHdr", "DemandDetail", "DemandHead",
    "DemandSchedule", "EmpBasic", "GLAccount", "GLCntrl", "GLCntrlAcct",
    "GLCntrlType", "GLJrnDtl", "GLJrnHed", "InvcDtl", "InvcHead",
    "InvcMisc", "JobAsmbl", "JobHead", "JobMtl", "JobOpDtl", "JobOper",
    "JobProd", "LaborDtl", "LaborHed", "OpMaster", "OrderDtl", "OrderHed",
    "OrderMsc", "OrderRel", "PODetail", "POHeader", "PORel", "Part",
    "PartBin", "PartClass", "PartCost", "PartPlant", "PartTran", "PartWhse",
    "PartWip", "ProdGrup", "ProjAnalHistory", "ProjCstHistory", "ProjPhase",
    "Project", "ProjectAnalysis", "ProjectCommit", "ProjectCst",
    "ProjectJobCost", "PurAgent", "RcvDtl", "RcvHead", "Resource",
    "ResourceGroup", "ResourceTimeUsed", "ResourceType", "SalesRep",
    "ShipDtl", "ShipHead", "ShipTo", "ShipVia", "Terms", "Vendor",
    "Warehse", "WhseBin",
})
QUERY_PARAMS = {
    "shipping_as_of": (("as_of", "limit"), ("as_of",)),
    "shipping_dod": (("from", "to", "limit"), ()),
    "shipping_logs": (("from", "to", "limit"), ()),
    "shipping_mom": (("as_of", "limit"), ()),
    "shipping_wow": (("as_of", "limit"), ()),
}
SHIPPING_ROW_FIELDS = (
    "Company", "PackNum", "ShipDate", "CustNum", "CustID", "PackLine",
    "OrderNum", "OrderLine", "PartNum", "OurInventoryShipQty",
)
SHIPPING_DOD_FIELDS = ("ship_day", "qty", "qty_prev", "qty_delta")
SHIPPING_COMPARISON_FIELDS = (
    "this_from", "this_to", "prev_from", "prev_to",
    "qty_this", "qty_prev", "qty_delta",
)


@dataclass(frozen=True)
class UpstreamContract:
    """A source-reviewed, fixed upstream mapping and response projection."""

    base_env: str
    path: str
    fields: tuple[str, ...]
    upstream_as_of_param: Optional[str] = None
    nested_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()


# Paths and field names verified against lake-api. Exclude nested diagnostics,
# integration metadata and free-form notes from the browser response.
APPROVED_CONTRACTS: Mapping[str, UpstreamContract] = {
    "health": UpstreamContract(
        "LAKE_API_BASE_URL", "/health",
        ("status", "service", "checked_at", "catalog_tables"),
    ),
    "freshness": UpstreamContract(
        "LAKE_API_BASE_URL", "/freshness",
        ("status", "service", "checked_at", "latest_snapshot_date",
         "latest_load_date", "tables_checked", "source"),
    ),
    "catalog": UpstreamContract(
        "LAKE_API_BASE_URL",
        "/catalog",
        ("status", "count", "by_class", "tables", "checked_at"),
        nested_fields=(
            ("by_class", ("scd2", "append", "snapshot")),
            ("tables", ("table", "class", "keys", "ud", "watermark")),
        ),
    ),
    "tables": UpstreamContract(
        "LAKE_API_BASE_URL",
        "/tables",
        ("status", "count", "by_class", "tables", "checked_at"),
        nested_fields=(
            ("by_class", ("scd2", "append", "snapshot")),
            ("tables", ("table", "class", "keys", "ud", "watermark")),
        ),
    ),
    "queries": UpstreamContract(
        "LAKE_API_BASE_URL",
        "/queries",
        ("status", "count", "queries", "checked_at"),
        nested_fields=(
            ("queries", ("name", "version", "status", "engine", "summary",
                         "tables", "params")),
        ),
    ),
    "shipping_logs": UpstreamContract(
        "LAKE_API_BASE_URL",
        "/queries/shipping_logs",
        ("status", "query", "version", "engine", "params", "returned", "rows",
         "checked_at"),
        nested_fields=(
            ("params", ("from", "to", "limit")),
            ("rows", SHIPPING_ROW_FIELDS),
        ),
    ),
    "wow": UpstreamContract(
        "LAKE_API_BASE_URL",
        "/wow",
        ("status", "query", "version", "engine", "params", "returned",
         "period", "metrics", "checked_at"),
        nested_fields=(
            ("params", ("as_of", "limit")),
            ("metrics", SHIPPING_COMPARISON_FIELDS),
        ),
    ),
    "mom": UpstreamContract(
        "LAKE_API_BASE_URL",
        "/mom",
        ("status", "query", "version", "engine", "params", "returned",
         "period", "metrics", "checked_at"),
        nested_fields=(
            ("params", ("as_of", "limit")),
            ("metrics", SHIPPING_COMPARISON_FIELDS),
        ),
    ),
}


def _make_client(**kwargs):
    """Seam for deterministic transport tests; production always uses httpx."""
    return httpx.AsyncClient(**kwargs)


def envelope(state: str, message: str, data=None) -> dict:
    return {"state": state, "message": message, "data": data}


def _json_response(status_code: int, state: str, message: str, data=None):
    return JSONResponse(
        status_code=status_code,
        content=envelope(state, message, data),
        headers={"Cache-Control": "no-store"},
    )


def _validated_base(value: str, base_env: str) -> Optional[str]:
    if (
        not value
        or any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            for character in value
        )
        or "\\" in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "mcp.colonydisplay.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or port not in (None, 443)
        or port is None and parsed.netloc.endswith(":")
    ):
        return None
    path = parsed.path.removesuffix("/")
    service = _SERVICE_PATHS.get(base_env)
    if (
        not service
        or not (path == service or path.startswith(service + "/"))
        or not _SAFE_PATH.fullmatch(path)
        or any(part in (".", "..") for part in path.split("/"))
    ):
        return None
    return urlunsplit(("https", "mcp.colonydisplay.com", path, "", ""))


def _validated_contract(contract: UpstreamContract) -> bool:
    path = contract.path
    return bool(
        path.startswith("/")
        and not path.startswith("//")
        and "://" not in path
        and "?" not in path
        and "#" not in path
        and "%" not in path
        and "\\" not in path
        and _SAFE_PATH.fullmatch(path)
        and all(part not in ("", ".", "..") for part in path.split("/")[1:])
        and contract.base_env in ("LAKE_HEALTH_BASE_URL", "LAKE_API_BASE_URL")
        and contract.fields
    )


def _validate_request_query(request: Request, report: str) -> Optional[str]:
    items = list(request.query_params.multi_items())
    if report != "pit":
        if items:
            raise ValueError("This report does not accept query parameters")
        return None
    if len(items) != 1 or items[0][0] != "asOf":
        raise ValueError("Provide exactly one asOf query parameter in YYYY-MM-DD format")
    value = items[0][1]
    if not _ISO_DATE.fullmatch(value):
        parsed = None
    else:
        try:
            parsed = datetime.date.fromisoformat(value)
        except ValueError:
            parsed = None
    if parsed is None or parsed > datetime.datetime.now(datetime.timezone.utc).date():
        raise ValueError("asOf must be a valid, non-future YYYY-MM-DD date")
    return value


def _finite_json(value, depth: int = 0) -> bool:
    if depth > 50:
        return False
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite_json(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _finite_json(item, depth + 1)
            for key, item in value.items()
        )
    return False


def _project(
    payload,
    fields: tuple[str, ...],
    nested_fields: tuple[tuple[str, tuple[str, ...]], ...] = (),
):
    nested = dict(nested_fields)

    def project_nested(value, allowed):
        if isinstance(value, dict):
            return {field: value[field] for field in allowed if field in value}
        if isinstance(value, list):
            rows = []
            for item in value:
                if isinstance(item, dict):
                    rows.append({
                        field: item[field] for field in allowed if field in item
                    })
            return rows
        return None

    def project_row(row):
        if not isinstance(row, dict):
            return None
        result = {}
        for field in fields:
            if field not in row:
                continue
            if field in nested:
                value = project_nested(row[field], nested[field])
                if value is not None:
                    result[field] = value
            else:
                result[field] = row[field]
        return result

    if isinstance(payload, dict):
        return project_row(payload)
    if isinstance(payload, list):
        rows = [project_row(row) for row in payload]
        return [row for row in rows if row]
    return None


async def _fetch(
    contract: UpstreamContract,
    base: str,
    as_of: Optional[str],
    upstream_params: Optional[Mapping[str, str | int]] = None,
):
    # Recheck the destination at the transport boundary. Never trust a caller
    # or environment value to widen the fixed service allowlist.
    base = _validated_base(base, contract.base_env)
    if not base or not _validated_contract(contract):
        return _json_response(503, "not_configured", "The DataLake service configuration is invalid")
    token = os.environ.get("LAKE_API_AUTH_TOKEN", "")
    if not token:
        return _json_response(
            503, "not_configured",
            "Missing required configuration: LAKE_API_AUTH_TOKEN. Set it in Replit Tools → Secrets",
        )
    if not _BEARER_TOKEN.fullmatch(token):
        return _json_response(503, "not_configured", _TOKEN_CONFIG_MESSAGE)
    headers = {
        "Accept": "application/json",
        "User-Agent": "colony-datalake-proxy/1",
        "Authorization": f"Bearer {token}",
    }
    params = dict(upstream_params or {})
    if as_of is not None:
        if not contract.upstream_as_of_param:
            return _json_response(200, "unavailable", "The PIT upstream date contract is not approved")
        params[contract.upstream_as_of_param] = as_of
    if not params:
        params = None
    timeout = httpx.Timeout(
        timeout=READ_TIMEOUT_SECONDS,
        connect=CONNECT_TIMEOUT_SECONDS,
        read=READ_TIMEOUT_SECONDS,
    )
    try:
        async def request_once():
            async with _make_client(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    f"{base}{contract.path}",
                    params=params,
                    headers=headers,
                ) as response:
                    if 300 <= response.status_code < 400:
                        return ("redirect", None)
                    if response.status_code >= 400:
                        return ("status", None)
                    content_type = response.headers.get("content-type", "").lower()
                    if "json" not in content_type:
                        return ("non_json", None)
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            return ("oversize", None)
                        chunks.append(chunk)
                    try:
                        return ("ok", json.loads(b"".join(chunks)))
                    except (
                        json.JSONDecodeError,
                        UnicodeDecodeError,
                        RecursionError,
                        ValueError,
                    ):
                        return ("non_json", None)

        outcome, payload = await asyncio.wait_for(
            request_once(), timeout=TOTAL_TIMEOUT_SECONDS
        )
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return _json_response(504, "upstream_error", "The DataLake service timed out")
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return _json_response(502, "upstream_error", "The DataLake service could not be reached")

    if outcome != "ok":
        messages = {
            "redirect": "The DataLake service returned an unsupported redirect",
            "status": "The DataLake service returned an error",
            "non_json": "The DataLake service returned an invalid response",
            "oversize": "The DataLake service response was too large",
        }
        return _json_response(502, "upstream_error", messages[outcome])
    if not isinstance(payload, (dict, list)) or not _finite_json(payload):
        return _json_response(502, "upstream_error", "The DataLake service returned an invalid response")
    # Even an approved field must not reflect the server credential.
    if token in json.dumps(payload, ensure_ascii=True):
        return _json_response(502, "upstream_error", "The DataLake service returned an invalid response")
    projected = _project(payload, contract.fields, contract.nested_fields)
    if projected in ({}, []):
        return _json_response(200, "empty", "No DataLake records were returned", projected)
    return _json_response(200, "ok", "DataLake report loaded", projected)


def create_datalake_router(
    require_section: Callable[..., Callable],
    trusted_preview_session: Optional[Callable[[Request], bool]] = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/datalake",
        tags=["datalake"],
        dependencies=[Depends(require_section("datalake"))],
    )

    def require_real_session(request: Request):
        real_session = getattr(request.state, "real_clerk_session", False)
        preview_session = bool(
            trusted_preview_session and trusted_preview_session(request)
        )
        if not real_session and not preview_session:
            raise HTTPException(status_code=403, detail="real_session_required")

    def parse_date(value: str, field: str) -> str:
        if not _ISO_DATE.fullmatch(value):
            parsed = None
        else:
            try:
                parsed = datetime.date.fromisoformat(value)
            except ValueError:
                parsed = None
        if parsed is None or parsed > datetime.datetime.now(
            datetime.timezone.utc
        ).date():
            raise ValueError(
                f"{field} must be a valid, non-future YYYY-MM-DD date"
            )
        return value

    def validated_params(
        request: Request,
        allowed: tuple[str, ...] = (),
        required: tuple[str, ...] = (),
    ) -> dict[str, str | int]:
        items = list(request.query_params.multi_items())
        seen = set()
        params: dict[str, str | int] = {}
        for key, value in items:
            if key not in allowed or key in seen:
                raise ValueError("The request contains unsupported query parameters")
            seen.add(key)
            if key in ("as_of", "from", "to"):
                params[key] = parse_date(value, key)
            elif key == "limit":
                try:
                    limit = int(value)
                except ValueError as exc:
                    raise ValueError("limit must be an integer from 1 to 500") from exc
                if limit < 1 or limit > 500:
                    raise ValueError("limit must be an integer from 1 to 500")
                params[key] = limit
            elif key == "table":
                if (
                    not _IDENTIFIER.fullmatch(value)
                    or value not in APPROVED_TABLES
                ):
                    raise ValueError("table is not approved")
                params[key] = value
        missing = [key for key in required if key not in params]
        if missing:
            raise ValueError(
                f"Missing required query parameter{'s' if len(missing) > 1 else ''}: "
                + ", ".join(missing)
            )
        if "from" in params and "to" in params and params["from"] > params["to"]:
            raise ValueError("from must be earlier than or equal to to")
        return params

    def validated_identifier(value: str, allowed: frozenset[str], label: str):
        if not _IDENTIFIER.fullmatch(value) or value not in allowed:
            raise ValueError(f"{label} is not approved")
        return value

    def configuration_error(base_env: str):
        raw_base = os.environ.get(base_env, "")
        if not raw_base:
            return _json_response(
                503,
                "not_configured",
                f"Missing required configuration: {base_env}. Set it in Replit Tools → Secrets",
            )
        if not _validated_base(raw_base, base_env):
            return _json_response(
                503,
                "not_configured",
                "The DataLake service configuration is invalid",
            )
        token = os.environ.get("LAKE_API_AUTH_TOKEN", "")
        if not token:
            return _json_response(
                503,
                "not_configured",
                "Missing required configuration: LAKE_API_AUTH_TOKEN. Set it in Replit Tools → Secrets",
            )
        if not _BEARER_TOKEN.fullmatch(token):
            return _json_response(
                503, "not_configured", _TOKEN_CONFIG_MESSAGE
            )
        return None

    async def proxy_contract(
        contract: UpstreamContract,
        *,
        as_of: Optional[str] = None,
        upstream_params: Optional[Mapping[str, str | int]] = None,
    ):
        if not _validated_contract(contract):
            return _json_response(
                200,
                "unavailable",
                "This report's upstream contract is not approved",
            )
        error = configuration_error(contract.base_env)
        if error is not None:
            return error
        raw_base = os.environ.get(contract.base_env, "")
        base = _validated_base(raw_base, contract.base_env)
        assert base is not None
        return await _fetch(
            contract,
            base,
            as_of,
            upstream_params=upstream_params,
        )

    async def report(request: Request, report_name: str):
        if report_name == "changes":
            return _json_response(
                200,
                "unavailable",
                "Change reporting is unavailable until an upstream contract is approved",
            )
        try:
            if report_name in ("wow", "mom"):
                as_of = None
                upstream_params = validated_params(
                    request, ("as_of", "limit")
                )
            else:
                as_of = _validate_request_query(request, report_name)
                upstream_params = None
        except ValueError as exc:
            return _json_response(400, "invalid_request", str(exc))
        contract = APPROVED_CONTRACTS.get(report_name)
        if contract is None:
            error = configuration_error("LAKE_API_BASE_URL")
            if error is not None:
                return error
            return _json_response(
                200,
                "unavailable",
                "This report is unavailable until its upstream contract is approved",
            )
        return await proxy_contract(
            contract,
            as_of=as_of,
            upstream_params=upstream_params,
        )

    def endpoint_for(report_name: str):
        async def endpoint(request: Request):
            return await report(request, report_name)
        return endpoint

    for report_name in _REPORTS:
        router.add_api_route(
            f"/{report_name}",
            endpoint_for(report_name),
            methods=["GET"],
            name=f"datalake-{report_name}",
            dependencies=[Depends(require_real_session)],
        )

    async def fixed_proxy(request: Request, contract_name: str):
        try:
            params = validated_params(request)
        except ValueError as exc:
            return _json_response(400, "invalid_request", str(exc))
        return await proxy_contract(APPROVED_CONTRACTS[contract_name])

    @router.get(
        "/catalog",
        name="datalake-catalog",
        dependencies=[Depends(require_real_session)],
    )
    async def catalog(request: Request):
        return await fixed_proxy(request, "catalog")

    @router.get(
        "/tables",
        name="datalake-tables",
        dependencies=[Depends(require_real_session)],
    )
    async def tables(request: Request):
        return await fixed_proxy(request, "tables")

    @router.get(
        "/queries",
        name="datalake-queries",
        dependencies=[Depends(require_real_session)],
    )
    async def queries(request: Request):
        return await fixed_proxy(request, "queries")

    def query_contract(name: str) -> UpstreamContract:
        if name == "shipping_logs":
            return APPROVED_CONTRACTS["shipping_logs"]
        row_fields = (
            SHIPPING_ROW_FIELDS
            if name == "shipping_as_of"
            else SHIPPING_DOD_FIELDS
            if name == "shipping_dod"
            else SHIPPING_COMPARISON_FIELDS
        )
        allowed_params, _required_params = QUERY_PARAMS[name]
        return UpstreamContract(
            "LAKE_API_BASE_URL",
            f"/queries/{name}",
            ("status", "query", "version", "engine", "tables", "params",
             "returned", "rows", "checked_at"),
            nested_fields=(
                ("params", allowed_params),
                ("rows", row_fields),
            ),
        )

    @router.get(
        "/queries/{name}",
        name="datalake-query",
        dependencies=[Depends(require_real_session)],
    )
    async def query(request: Request, name: str):
        try:
            name = validated_identifier(name, APPROVED_QUERY_NAMES, "query")
            allowed, required = QUERY_PARAMS[name]
            params = validated_params(request, allowed, required)
        except ValueError as exc:
            return _json_response(400, "invalid_request", str(exc))
        return await proxy_contract(
            query_contract(name),
            upstream_params=params,
        )

    table_fields = (
        "status", "table", "class", "mode", "keys", "as_of", "row_count",
        "returned", "checked_at",
    )

    @router.get(
        "/current/{table}",
        name="datalake-current-table",
        dependencies=[Depends(require_real_session)],
    )
    async def current_table(request: Request, table: str):
        try:
            table = validated_identifier(table, APPROVED_TABLES, "table")
            params = validated_params(request, ("limit",))
        except ValueError as exc:
            return _json_response(400, "invalid_request", str(exc))
        return await proxy_contract(
            UpstreamContract(
                "LAKE_API_BASE_URL", f"/current/{table}", table_fields
            ),
            upstream_params=params,
        )

    @router.get(
        "/pit/{table}",
        name="datalake-pit-table",
        dependencies=[Depends(require_real_session)],
    )
    async def pit_table(request: Request, table: str):
        try:
            table = validated_identifier(table, APPROVED_TABLES, "table")
            params = validated_params(
                request, ("as_of", "limit"), ("as_of",)
            )
        except ValueError as exc:
            return _json_response(400, "invalid_request", str(exc))
        return await proxy_contract(
            UpstreamContract(
                "LAKE_API_BASE_URL", f"/pit/{table}", table_fields
            ),
            upstream_params=params,
        )

    @router.get(
        "/as-of",
        name="datalake-as-of",
        dependencies=[Depends(require_real_session)],
    )
    async def as_of(request: Request):
        try:
            params = validated_params(
                request,
                ("table", "as_of", "limit"),
                ("table", "as_of"),
            )
        except ValueError as exc:
            return _json_response(400, "invalid_request", str(exc))
        return await proxy_contract(
            UpstreamContract(
                "LAKE_API_BASE_URL", "/as-of", table_fields
            ),
            upstream_params=params,
        )

    @router.api_route("/{unknown_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def unknown_datalake_route():
        return _json_response(404, "invalid_request", "Unknown DataLake API route")

    return router