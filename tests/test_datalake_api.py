"""Security and failure-contract coverage for the privileged DataLake proxy."""

import asyncio
import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import datalake_api
import po_api


AUTH = {"Authorization": "Bearer admin-session"}
TEST_LAKE_TOKEN = "test-only-lake-token_123456789"
HEALTH_BASE = "https://mcp.colonydisplay.com/lake-health"
API_BASE = "https://mcp.colonydisplay.com/lake-api"
PRODUCTION_CONTRACTS = dict(datalake_api.APPROVED_CONTRACTS)
FAKE_HEALTH_CONTRACT = datalake_api.UpstreamContract(
    base_env="LAKE_API_BASE_URL",
    path="/fake-approved/health",
    fields=("status", "updatedAt"),
)
FAKE_PIT_CONTRACT = datalake_api.UpstreamContract(
    base_env="LAKE_API_BASE_URL",
    path="/fake-approved/inventory",
    fields=("part", "quantity", "asOf"),
    upstream_as_of_param="fakeDate",
)
DISABLED_LAKE_HEALTH_CONTRACT = datalake_api.UpstreamContract(
    base_env="LAKE_HEALTH_BASE_URL",
    path="/health",
    fields=("status",),
)


class FakeClerk:
    def authenticate_request(self, request, _options):
        valid = request.headers.get("authorization") == "Bearer admin-session"
        return SimpleNamespace(
            is_signed_in=valid,
            payload={"sub": "admin_test"} if valid else None,
        )


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setattr(po_api, "_clerk", FakeClerk())
    monkeypatch.setattr(
        po_api,
        "_clerk_user_info",
        lambda _: {
            "allowed": True,
            "email": "admin@colonydisplay.com",
            "name": "Lake Admin",
        },
    )
    monkeypatch.setattr(
        po_api,
        "_get_app_user",
        lambda *_: {
            "id": 1,
            "email": "admin@colonydisplay.com",
            "name": "Lake Admin",
            "active": True,
            "role": "admin",
        },
    )
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", {})
    monkeypatch.delenv("LAKE_HEALTH_BASE_URL", raising=False)
    monkeypatch.delenv("LAKE_API_BASE_URL", raising=False)
    monkeypatch.setenv("LAKE_API_AUTH_TOKEN", TEST_LAKE_TOKEN)
    return TestClient(po_api.app)


def mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    monkeypatch.setattr(datalake_api, "_make_client", factory)


@pytest.mark.parametrize(
    ("value", "base_env", "expected"),
    [
        (HEALTH_BASE, "LAKE_HEALTH_BASE_URL", HEALTH_BASE),
        (
            f"{HEALTH_BASE}/v1/status/",
            "LAKE_HEALTH_BASE_URL",
            f"{HEALTH_BASE}/v1/status",
        ),
        (
            "https://mcp.colonydisplay.com:not-a-port/lake-api",
            "LAKE_API_BASE_URL",
            None,
        ),
        (
            "https://mcp.colonydisplay.com:443/lake-api",
            "LAKE_API_BASE_URL",
            API_BASE,
        ),
    ],
)
def test_validated_base_accepts_only_its_exact_service_tree(
    value, base_env, expected
):
    assert datalake_api._validated_base(value, base_env) == expected


def test_production_contracts_use_only_lake_api():
    assert set(PRODUCTION_CONTRACTS) == {
        "health",
        "freshness",
        "catalog",
        "tables",
        "queries",
        "shipping_logs",
        "wow",
        "mom",
    }
    assert {
        contract.base_env for contract in PRODUCTION_CONTRACTS.values()
    } == {"LAKE_API_BASE_URL"}
    assert PRODUCTION_CONTRACTS["health"] == datalake_api.UpstreamContract(
        "LAKE_API_BASE_URL",
        "/health",
        ("status", "service", "checked_at", "catalog_tables"),
    )
    assert PRODUCTION_CONTRACTS["freshness"] == datalake_api.UpstreamContract(
        "LAKE_API_BASE_URL",
        "/freshness",
        (
            "status",
            "service",
            "checked_at",
            "latest_snapshot_date",
            "latest_load_date",
            "tables_checked",
            "source",
        ),
    )
    assert PRODUCTION_CONTRACTS["shipping_logs"].path == (
        "/queries/shipping_logs"
    )
    assert dict(PRODUCTION_CONTRACTS["shipping_logs"].nested_fields)["rows"] == (
        "Company",
        "PackNum",
        "ShipDate",
        "CustNum",
        "CustID",
        "PackLine",
        "OrderNum",
        "OrderLine",
        "PartNum",
        "OurInventoryShipQty",
    )


@pytest.mark.parametrize("report", ["health", "freshness"])
def test_production_health_contract_projection_excludes_unapproved_fields(report):
    contract = PRODUCTION_CONTRACTS[report]
    payload = {
        **{field: f"value-for-{field}" for field in contract.fields},
        "diagnostics": {"private": True},
        "linear": "internal",
        "notes": "private",
    }

    projected = datalake_api._project(payload, contract.fields)

    assert set(projected) == set(contract.fields)
    assert {"diagnostics", "linear", "notes"}.isdisjoint(projected)


def test_active_real_admin_receives_capability_and_missing_config(admin_client, monkeypatch):
    monkeypatch.delenv("LAKE_API_AUTH_TOKEN", raising=False)
    me = admin_client.get("/me", headers=AUTH)
    report = admin_client.get("/api/datalake/health", headers=AUTH)

    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    assert "datalake" in me.json()["sections"]
    assert report.status_code == 503
    assert report.json() == {
        "state": "not_configured",
        "message": "Missing required configuration: LAKE_API_BASE_URL. Set it in Replit Tools → Secrets",
        "data": None,
    }
    assert report.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("report", "contract", "expected_base"),
    [
        ("health", FAKE_HEALTH_CONTRACT, API_BASE),
        ("wow", datalake_api.UpstreamContract(
            "LAKE_API_BASE_URL", "/fake-approved/wow", ("status",)
        ), API_BASE),
    ],
)
def test_unset_base_has_no_default(admin_client, monkeypatch, report, contract, expected_base):
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", {report: contract})
    monkeypatch.setattr(
        datalake_api, "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )
    response = admin_client.get(f"/api/datalake/{report}", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"
    assert contract.base_env in response.json()["message"]


@pytest.mark.parametrize("report", ["health", "freshness", "wow", "mom", "pit?asOf=2020-01-01"])
def test_configured_bases_still_require_secret(admin_client, monkeypatch, report):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.delenv("LAKE_API_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        datalake_api, "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )
    response = admin_client.get(f"/api/datalake/{report}", headers=AUTH)
    assert response.status_code == 503
    assert "LAKE_API_AUTH_TOKEN" in response.json()["message"]
    assert "Secrets" in response.json()["message"]


@pytest.mark.parametrize("role", ["viewer", "warehouse", "purchasing", "none"])
def test_non_admin_roles_are_denied_before_proxy(admin_client, monkeypatch, role):
    monkeypatch.setattr(
        po_api, "_get_app_user", lambda *_: {"active": True, "role": role}
    )
    monkeypatch.setattr(
        datalake_api,
        "_fetch",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not proxy")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"detail": "section_forbidden"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("member", [None, {"active": False, "role": "admin"}])
def test_missing_or_inactive_members_are_denied(admin_client, monkeypatch, member):
    monkeypatch.setattr(po_api, "_get_app_user", lambda *_: member)
    monkeypatch.setattr(
        datalake_api,
        "_fetch",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not proxy")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"detail": "no_access"}


def test_wrong_domain_is_denied_before_membership_or_proxy(admin_client, monkeypatch):
    monkeypatch.setattr(
        po_api,
        "_clerk_user_info",
        lambda _: {"allowed": False, "email": "outsider@example.com", "name": ""},
    )
    monkeypatch.setattr(
        po_api,
        "_get_app_user",
        lambda *_: (_ for _ in ()).throw(AssertionError("no membership lookup")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 403
    assert "colonydisplay.com" in response.json()["detail"]


def test_unsigned_and_invalid_sessions_cannot_fall_into_preview(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", False)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    monkeypatch.setattr(po_api, "_clerk", FakeClerk())
    monkeypatch.setattr(
        datalake_api,
        "_fetch",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not proxy")),
    )
    with TestClient(po_api.app, base_url="http://testserver") as client:
        preview_me = client.get("/me")
        unsigned = client.get("/api/datalake/health")
        invalid = client.get(
            "/api/datalake/health", headers={"Authorization": "Bearer invalid"}
        )

    assert "datalake" not in preview_me.json()["sections"]
    assert unsigned.status_code == 403
    assert unsigned.json() == {"detail": "real_session_required"}
    assert invalid.status_code == 401
    assert invalid.json() == {"detail": "Not authenticated"}


def test_trusted_live_preview_can_read_mocked_upstream_without_fake_clerk(
    monkeypatch,
):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", True)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setenv("LAKE_API_AUTH_TOKEN", TEST_LAKE_TOKEN)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={"status": "healthy", "updatedAt": "2026-01-01", "private": 1},
        )

    mock_client(monkeypatch, handler)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        me = client.get("/me")
        response = client.get("/api/datalake/health")

    assert me.json()["liveData"] is True
    assert "datalake" in me.json()["sections"]
    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "healthy",
        "updatedAt": "2026-01-01",
    }
    assert seen[0].headers["authorization"] == f"Bearer {TEST_LAKE_TOKEN}"


def test_live_preview_datalake_still_rejects_invalid_browser_token(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", True)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    monkeypatch.setattr(po_api, "_clerk", FakeClerk())
    monkeypatch.setattr(
        datalake_api,
        "_fetch",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not proxy")),
    )

    with TestClient(po_api.app, base_url="http://testserver") as client:
        response = client.get(
            "/api/datalake/health",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_configured_base_without_reviewed_contract_does_not_call_network(
    admin_client, monkeypatch
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get("/api/datalake/freshness", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"


@pytest.mark.parametrize(
    "contract",
    [
        datalake_api.UpstreamContract(
            "LAKE_API_BASE_URL", "//evil.invalid/path", ("status",)
        ),
        datalake_api.UpstreamContract(
            "LAKE_API_BASE_URL", "/safe/../private", ("status",)
        ),
        datalake_api.UpstreamContract(
            "LAKE_API_BASE_URL", "/safe/%2e%2e/private", ("status",)
        ),
        datalake_api.UpstreamContract(
            "UNAPPROVED_BASE_URL", "/wrong-base/health", ("status",)
        ),
    ],
)
def test_unreviewed_contract_destinations_cannot_override_fixed_mapping(
    admin_client, monkeypatch, contract
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": contract}
    )
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"


@pytest.mark.parametrize(
    "base",
    [
        "http://mcp.colonydisplay.com/lake-api",
        "https://user:password@mcp.colonydisplay.com/lake-api",
        "https://mcp.colonydisplay.com/lake-api?token=secret",
        "https://mcp.colonydisplay.com/lake-api#fragment",
        "//mcp.colonydisplay.com/lake-api",
        " https://mcp.colonydisplay.com/lake-api",
        "https://mcp.colonydisplay.com/lake-api/path with space",
        "https://mcp.colonydisplay.com/lake-api\\private",
        "https://mcp.colonydisplay.com/lake-api/\nprivate",
        "https://mcp.colonydisplay.com/lake-api/\x7fprivate",
        "https://mcp.colonydisplay.com:444/lake-api",
        "https://evil.invalid/lake-api",
        "https://mcp.colonydisplay.com/lake-health",
        "https://mcp.colonydisplay.com/lake-api/%2e%2e/private",
        "https://mcp.colonydisplay.com/lake-api/../private",
        "https://mcp.colonydisplay.com/lake-api//private",
        "https://mcp.colonydisplay.com/lake-api/%70rivate",
    ],
)
def test_invalid_server_base_is_rejected_without_network(
    admin_client, monkeypatch, base
):
    monkeypatch.setenv("LAKE_API_BASE_URL", base)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"
    assert "evil.invalid" not in response.text
    assert "secret" not in response.text


def test_fetch_defensively_rejects_invalid_base_before_creating_client(monkeypatch):
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = asyncio.run(
        datalake_api._fetch(
            FAKE_HEALTH_CONTRACT,
            "https://evil.invalid/lake-api",
            None,
        )
    )

    assert response.status_code == 503
    assert b"evil.invalid" not in response.body
    assert TEST_LAKE_TOKEN.encode() not in response.body


def test_fetch_sends_lake_token_to_lake_health(monkeypatch):
    monkeypatch.setenv("LAKE_API_AUTH_TOKEN", TEST_LAKE_TOKEN)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "healthy"})

    mock_client(monkeypatch, handler)

    response = asyncio.run(
        datalake_api._fetch(
            DISABLED_LAKE_HEALTH_CONTRACT,
            HEALTH_BASE,
            None,
        )
    )

    assert response.status_code == 200
    assert b'"state":"ok"' in response.body
    assert seen[0].headers["authorization"] == f"Bearer {TEST_LAKE_TOKEN}"
    assert seen[0].url.host == "mcp.colonydisplay.com"
    assert seen[0].url.path.startswith("/lake-health/")


@pytest.mark.parametrize("report", ["health", "freshness"])
def test_configured_health_base_alone_cannot_call_health_service(
    admin_client, monkeypatch, report
):
    monkeypatch.setenv("LAKE_HEALTH_BASE_URL", HEALTH_BASE)
    monkeypatch.delenv("LAKE_API_BASE_URL", raising=False)
    monkeypatch.setattr(
        datalake_api,
        "APPROVED_CONTRACTS",
        {report: PRODUCTION_CONTRACTS[report]},
    )
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get(f"/api/datalake/{report}", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"
    assert "LAKE_API_BASE_URL" in response.json()["message"]
    assert "LAKE_HEALTH_BASE_URL" not in response.json()["message"]


@pytest.mark.parametrize(
    ("base_env", "value"),
    [
        ("LAKE_HEALTH_BASE_URL", API_BASE),
        ("LAKE_API_BASE_URL", HEALTH_BASE),
        ("LAKE_HEALTH_BASE_URL", "https://mcp.colonydisplay.com/lake-healthish"),
        ("LAKE_API_BASE_URL", "https://mcp.colonydisplay.com/lake-api.evil"),
    ],
)
def test_service_prefixes_cannot_be_crossed_or_confused(
    admin_client, monkeypatch, base_env, value
):
    report = "health" if base_env == "LAKE_HEALTH_BASE_URL" else "wow"
    contract = FAKE_HEALTH_CONTRACT if report == "health" else datalake_api.UpstreamContract(
        "LAKE_API_BASE_URL", "/fake-approved/wow", ("status",)
    )
    monkeypatch.setenv(base_env, value)
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", {report: contract})
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get(f"/api/datalake/{report}", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"


@pytest.mark.parametrize(
    "token",
    ["", " ", "contains whitespace", "line\nbreak", "Bearer nested", "bad\x7fvalue"],
)
def test_missing_or_invalid_lake_token_is_not_configured_without_network(
    admin_client, monkeypatch, token
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setenv("LAKE_API_AUTH_TOKEN", token)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"
    if token.strip():
        assert token.strip() not in response.text


def test_gateway_tokens_are_never_used_as_lake_token(admin_client, monkeypatch):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.delenv("LAKE_API_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("GATEWAY_TOKEN", "gateway-only-secret")
    monkeypatch.setenv("LAKE_GATEWAY_TOKEN", "lake-gateway-only-secret")
    monkeypatch.setenv("MCP_GATEWAY_AUTH_TOKEN", "mcp-gateway-only-secret")
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"
    assert "gateway-only-secret" not in response.text
    assert "mcp-gateway-only-secret" not in response.text


@pytest.mark.parametrize(
    ("report", "base_env", "base", "path"),
    [
        ("health", "LAKE_API_BASE_URL", API_BASE, "/api/datalake/health"),
        (
            "freshness",
            "LAKE_API_BASE_URL",
            API_BASE,
            "/api/datalake/freshness",
        ),
        ("wow", "LAKE_API_BASE_URL", API_BASE, "/api/datalake/wow"),
        ("mom", "LAKE_API_BASE_URL", API_BASE, "/api/datalake/mom"),
        (
            "pit",
            "LAKE_API_BASE_URL",
            API_BASE,
            "/api/datalake/pit?asOf=2020-01-01",
        ),
    ],
)
def test_every_upstream_report_requires_lake_token_before_network(
    admin_client, monkeypatch, report, base_env, base, path
):
    contract = datalake_api.UpstreamContract(
        base_env,
        f"/fake-approved/{report}",
        ("status",),
        "fakeDate" if report == "pit" else None,
    )
    monkeypatch.setenv(base_env, base)
    monkeypatch.delenv("LAKE_API_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", {report: contract})
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get(path, headers=AUTH)

    assert response.status_code == 503
    assert response.json()["state"] == "not_configured"


def test_approved_mock_contract_uses_fixed_path_projects_fields_and_omits_credentials(
    admin_client, monkeypatch
):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": "healthy",
                "updatedAt": "2026-01-01T00:00:00Z",
                "privateToken": "must-not-pass",
            },
        )

    monkeypatch.setenv("LAKE_API_BASE_URL", f"{API_BASE}/v1")
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    mock_client(monkeypatch, handler)

    response = admin_client.get(
        "/api/datalake/health",
        headers={
            **AUTH,
            "Cookie": "session=private",
            "Clerk-Secret-Key": "private-secret",
            "X-Untrusted": "private-value",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "healthy",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == f"{API_BASE}/v1/fake-approved/health"
    assert request.headers["authorization"] == f"Bearer {TEST_LAKE_TOKEN}"
    assert request.headers["authorization"] != AUTH["Authorization"]
    assert "cookie" not in request.headers
    assert "clerk-secret-key" not in request.headers
    assert "x-untrusted" not in request.headers


def test_shipping_logs_uses_lake_token_and_projects_approved_rows(
    admin_client, monkeypatch
):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "query": "shipping_logs",
                "version": 1,
                "engine": "duckdb",
                "tables": ["ShipHead", "ShipDtl", "Customer"],
                "params": {"limit": 100, "private": "omit"},
                "returned": 1,
                "rows": [{
                    "Company": "EPIC",
                    "PackNum": 42,
                    "ShipDate": "2026-09-17",
                    "CustNum": 7,
                    "CustID": "CUSTOMER",
                    "PackLine": 1,
                    "OrderNum": 9,
                    "OrderLine": 2,
                    "PartNum": "PART",
                    "OurInventoryShipQty": "3.00",
                    "private": "omit",
                }],
                "note": "omit",
                "checked_at": "2026-09-19T10:00:00Z",
                "private": "omit",
            },
        )

    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api,
        "APPROVED_CONTRACTS",
        {"shipping_logs": PRODUCTION_CONTRACTS["shipping_logs"]},
    )
    mock_client(monkeypatch, handler)

    response = admin_client.get(
        "/api/datalake/queries/shipping_logs",
        headers={
            **AUTH,
            "Cookie": "session=browser-private",
            "Clerk-Secret-Key": "clerk-private",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["query"] == "shipping_logs"
    assert data["params"] == {"limit": 100}
    assert data["rows"] == [{
        "Company": "EPIC",
        "PackNum": 42,
        "ShipDate": "2026-09-17",
        "CustNum": 7,
        "CustID": "CUSTOMER",
        "PackLine": 1,
        "OrderNum": 9,
        "OrderLine": 2,
        "PartNum": "PART",
        "OurInventoryShipQty": "3.00",
    }]
    assert "private" not in response.text
    assert "note" not in data
    assert "tables" not in data
    assert seen[0].url.path == "/lake-api/queries/shipping_logs"
    assert seen[0].headers["authorization"] == f"Bearer {TEST_LAKE_TOKEN}"
    assert seen[0].headers["authorization"] != AUTH["Authorization"]
    assert "cookie" not in seen[0].headers
    assert "clerk-secret-key" not in seen[0].headers


@pytest.mark.parametrize(
    ("browser_path", "upstream_path", "upstream_params"),
    [
        ("/api/datalake/catalog", "/lake-api/catalog", {}),
        ("/api/datalake/tables", "/lake-api/tables", {}),
        ("/api/datalake/queries", "/lake-api/queries", {}),
        ("/api/datalake/freshness", "/lake-api/freshness", {}),
        ("/api/datalake/wow", "/lake-api/wow", {}),
        ("/api/datalake/mom", "/lake-api/mom", {}),
        (
            "/api/datalake/current/ShipHead?limit=5",
            "/lake-api/current/ShipHead",
            {"limit": "5"},
        ),
        (
            "/api/datalake/pit/ShipHead?as_of=2026-09-17&limit=5",
            "/lake-api/pit/ShipHead",
            {"as_of": "2026-09-17", "limit": "5"},
        ),
        (
            "/api/datalake/as-of?table=ShipHead&as_of=2026-09-17",
            "/lake-api/as-of",
            {"table": "ShipHead", "as_of": "2026-09-17"},
        ),
    ],
)
def test_required_read_only_routes_use_fixed_upstream_paths(
    admin_client,
    monkeypatch,
    browser_path,
    upstream_path,
    upstream_params,
):
    seen = []
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", PRODUCTION_CONTRACTS)

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "ok", "rows": []})

    mock_client(monkeypatch, handler)
    response = admin_client.get(browser_path, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == "ok"
    assert len(seen) == 1
    assert seen[0].url.path == upstream_path
    assert dict(seen[0].url.params) == upstream_params
    assert seen[0].headers["authorization"] == f"Bearer {TEST_LAKE_TOKEN}"


@pytest.mark.parametrize(
    ("browser_path", "row", "expected_row_keys", "upstream_params"),
    [
        (
            "/api/datalake/queries/shipping_as_of?as_of=2026-09-17&limit=1",
            {
                "Company": "EPIC",
                "PackNum": 1,
                "ShipDate": "2026-09-17",
                "CustNum": 2,
                "CustID": "CUSTOMER",
                "PackLine": 3,
                "OrderNum": 4,
                "OrderLine": 5,
                "PartNum": "PART",
                "OurInventoryShipQty": "6.00",
                "private": "omit",
            },
            set(datalake_api.SHIPPING_ROW_FIELDS),
            {"as_of": "2026-09-17", "limit": "1"},
        ),
        (
            "/api/datalake/queries/shipping_dod?from=2026-09-16&to=2026-09-17&limit=1",
            {
                "ship_day": "2026-09-17",
                "qty": 10,
                "qty_prev": 8,
                "qty_delta": 2,
                "private": "omit",
            },
            set(datalake_api.SHIPPING_DOD_FIELDS),
            {"from": "2026-09-16", "to": "2026-09-17", "limit": "1"},
        ),
        (
            "/api/datalake/queries/shipping_wow?as_of=2026-09-17&limit=1",
            {
                "this_from": "2026-09-11",
                "this_to": "2026-09-17",
                "prev_from": "2026-09-04",
                "prev_to": "2026-09-10",
                "qty_this": 10,
                "qty_prev": 8,
                "qty_delta": 2,
                "private": "omit",
            },
            set(datalake_api.SHIPPING_COMPARISON_FIELDS),
            {"as_of": "2026-09-17", "limit": "1"},
        ),
        (
            "/api/datalake/queries/shipping_mom?as_of=2026-09-17&limit=1",
            {
                "this_from": "2026-09-01",
                "this_to": "2026-09-17",
                "prev_from": "2026-08-01",
                "prev_to": "2026-08-31",
                "qty_this": 10,
                "qty_prev": 8,
                "qty_delta": 2,
                "private": "omit",
            },
            set(datalake_api.SHIPPING_COMPARISON_FIELDS),
            {"as_of": "2026-09-17", "limit": "1"},
        ),
    ],
)
def test_registered_shipping_queries_project_nested_fields(
    admin_client,
    monkeypatch,
    browser_path,
    row,
    expected_row_keys,
    upstream_params,
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", PRODUCTION_CONTRACTS)

    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "query": "approved-query",
                "version": 1,
                "engine": "duckdb",
                "tables": ["ShipHead", "ShipDtl"],
                "params": {**upstream_params, "private": "omit"},
                "returned": 1,
                "rows": [row],
                "note": "omit",
                "checked_at": "2026-09-19T10:00:00Z",
            },
        )

    mock_client(monkeypatch, handler)
    response = admin_client.get(browser_path, headers=AUTH)

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data["rows"][0]) == expected_row_keys
    assert set(data["params"]) == set(upstream_params)
    assert "private" not in response.text
    assert "note" not in data


@pytest.mark.parametrize(
    "browser_path",
    [
        "/api/datalake/current/ShipHead?limit=1",
        "/api/datalake/pit/ShipHead?as_of=2026-09-17&limit=1",
        "/api/datalake/as-of?table=ShipHead&as_of=2026-09-17&limit=1",
    ],
)
def test_table_metadata_routes_exclude_unreviewed_rows_and_notes(
    admin_client, monkeypatch, browser_path
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", PRODUCTION_CONTRACTS)
    mock_client(
        monkeypatch,
        lambda _request: httpx.Response(
            200,
            json={
                "status": "ok",
                "table": "ShipHead",
                "class": "scd2",
                "row_count": 1,
                "returned": 1,
                "rows": [{"PackNum": 1, "privateSecret": "must-not-pass"}],
                "note": "must-not-pass",
                "checked_at": "2026-09-19T10:00:00Z",
            },
        ),
    )

    response = admin_client.get(browser_path, headers=AUTH)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table"] == "ShipHead"
    assert data["returned"] == 1
    assert "rows" not in data
    assert "note" not in data
    assert "must-not-pass" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/datalake/queries/not_approved",
        "/api/datalake/queries/shipping_logs?url=https://evil.invalid",
        "/api/datalake/current/NotApproved",
        "/api/datalake/pit/ShipHead",
        "/api/datalake/pit/ShipHead?as_of=2999-01-01",
        "/api/datalake/as-of?as_of=2026-09-17",
        "/api/datalake/as-of?table=NotApproved&as_of=2026-09-17",
    ],
)
def test_dynamic_route_allowlists_reject_unknown_identifiers_and_parameters(
    admin_client, monkeypatch, path
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(datalake_api, "APPROVED_CONTRACTS", PRODUCTION_CONTRACTS)
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get(path, headers=AUTH)

    assert response.status_code == 400
    assert response.json()["state"] == "invalid_request"


def test_upstream_cannot_reflect_lake_token_into_response(admin_client, monkeypatch):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    mock_client(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json={"status": "healthy", "privateToken": TEST_LAKE_TOKEN},
        ),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 502
    assert response.json()["state"] == "upstream_error"
    assert TEST_LAKE_TOKEN not in response.text


def test_pit_translates_only_reviewed_date_parameter(admin_client, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json=[{"part": "A", "quantity": 4, "asOf": "2026-01-02", "secret": 1}],
        )

    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"pit": FAKE_PIT_CONTRACT}
    )
    mock_client(monkeypatch, handler)

    response = admin_client.get(
        "/api/datalake/pit?asOf=2026-01-02",
        headers={
            **AUTH,
            "Cookie": "session=browser-private",
            "Clerk-Secret-Key": "clerk-private",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {"part": "A", "quantity": 4, "asOf": "2026-01-02"}
    ]
    assert seen[0].url.path == "/lake-api/fake-approved/inventory"
    assert dict(seen[0].url.params) == {"fakeDate": "2026-01-02"}
    assert seen[0].headers["authorization"] == f"Bearer {TEST_LAKE_TOKEN}"
    assert TEST_LAKE_TOKEN != AUTH["Authorization"].removeprefix("Bearer ")
    assert "cookie" not in seen[0].headers
    assert "clerk-secret-key" not in seen[0].headers


@pytest.mark.parametrize(
    "path",
    [
        "/api/datalake/pit",
        "/api/datalake/pit?asOf=2026-01-02&asOf=2026-01-03",
        "/api/datalake/pit?asOf=2026-01-02&url=https://evil.invalid",
        "/api/datalake/pit?asOf=2026-02-30",
        "/api/datalake/pit?asOf=2999-01-01",
        "/api/datalake/health?asOf=2026-01-02",
    ],
)
def test_query_allowlist_rejects_missing_extra_duplicate_or_invalid_values(
    admin_client, monkeypatch, path
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get(path, headers=AUTH)

    assert response.status_code == 400
    assert response.json()["state"] == "invalid_request"


def test_changes_is_explicit_placeholder_and_never_calls_upstream(
    admin_client, monkeypatch
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.delenv("LAKE_API_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.get("/api/datalake/changes", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"
    assert response.json()["data"] is None


@pytest.mark.parametrize(
    ("upstream", "expected_status", "message_fragment"),
    [
        (httpx.Response(302, headers={"Location": "https://evil.invalid"}), 502, "redirect"),
        (httpx.Response(500, text="secret database failure"), 502, "error"),
        (httpx.Response(200, text="<html>private</html>"), 502, "invalid"),
        (
            httpx.Response(
                200,
                content=b"{broken",
                headers={"Content-Type": "application/json"},
            ),
            502,
            "invalid",
        ),
        (
            httpx.Response(
                200,
                content=b"x" * (datalake_api.MAX_RESPONSE_BYTES + 1),
                headers={"Content-Type": "application/json"},
            ),
            502,
            "large",
        ),
        (
            httpx.Response(
                200,
                content=b'{"status": NaN}',
                headers={"Content-Type": "application/json"},
            ),
            502,
            "invalid",
        ),
        (
            httpx.Response(
                200,
                content=(b"[" * 1100) + b"0" + (b"]" * 1100),
                headers={"Content-Type": "application/json"},
            ),
            502,
            "invalid",
        ),
        (
            httpx.Response(
                200,
                content=b'{"status": ' + (b"9" * 5000) + b"}",
                headers={"Content-Type": "application/json"},
            ),
            502,
            "invalid",
        ),
    ],
)
def test_upstream_redirect_error_nonjson_malformed_oversize_and_nonfinite_are_sanitized(
    admin_client, monkeypatch, upstream, expected_status, message_fragment
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    mock_client(monkeypatch, lambda _request: upstream)

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == expected_status
    assert response.json()["state"] == "upstream_error"
    assert message_fragment in response.json()["message"].lower()
    assert "evil.invalid" not in response.text
    assert "secret database failure" not in response.text
    assert "private" not in response.text


def test_upstream_timeout_is_sanitized(admin_client, monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("private upstream timeout", request=request)

    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    mock_client(monkeypatch, timeout)

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 504
    assert response.json()["state"] == "upstream_error"
    assert "private" not in response.text


def test_empty_projected_data_has_explicit_empty_state(admin_client, monkeypatch):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    mock_client(monkeypatch, lambda _: httpx.Response(200, json={"unknown": 1}))

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == "empty"
    assert response.json()["data"] == {}


def test_list_rows_without_approved_fields_are_empty_not_ok(
    admin_client, monkeypatch
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    mock_client(
        monkeypatch,
        lambda _: httpx.Response(200, json=[{"private": "not approved"}]),
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == "empty"
    assert response.json()["data"] == []


def test_invalid_url_from_http_client_is_sanitized(admin_client, monkeypatch):
    class InvalidUrlClient:
        async def __aenter__(self):
            raise httpx.InvalidURL("private malformed destination")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api, "APPROVED_CONTRACTS", {"health": FAKE_HEALTH_CONTRACT}
    )
    monkeypatch.setattr(
        datalake_api, "_make_client", lambda **_kwargs: InvalidUrlClient()
    )

    response = admin_client.get("/api/datalake/health", headers=AUTH)

    assert response.status_code == 502
    assert response.json()["state"] == "upstream_error"
    assert "private" not in response.text


def test_unknown_datalake_api_is_json_not_static_html(admin_client):
    response = admin_client.get("/api/datalake/not-approved", headers=AUTH)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["state"] == "invalid_request"


def test_proxy_routes_are_get_only_and_never_passthrough_methods(
    admin_client, monkeypatch
):
    monkeypatch.setenv("LAKE_API_BASE_URL", API_BASE)
    monkeypatch.setattr(
        datalake_api,
        "_make_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call network")),
    )

    response = admin_client.post("/api/datalake/health", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["state"] == "invalid_request"


def test_exact_datalake_deep_links_serve_only_exported_page(
    admin_client, monkeypatch, tmp_path
):
    page = tmp_path / "datalake.html"
    page.write_text("<!doctype html><title>DataLake export</title>", encoding="utf-8")
    monkeypatch.setattr(po_api, "UI_DIST", tmp_path)

    direct = admin_client.get("/datalake")
    slash = admin_client.get("/datalake/")

    assert direct.status_code == 200
    assert slash.status_code == 200
    assert "DataLake export" in direct.text
    assert "DataLake export" in slash.text


def test_unbuilt_datalake_deep_link_returns_narrow_404(
    admin_client, monkeypatch, tmp_path
):
    monkeypatch.setattr(po_api, "UI_DIST", tmp_path)

    response = admin_client.get("/datalake")

    assert response.status_code == 404
    assert response.json() == {"detail": "DataLake page is not built"}