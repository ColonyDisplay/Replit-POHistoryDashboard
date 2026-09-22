"""Safety checks for the development-only unsigned admin preview."""

import datetime
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import po_api


def test_preview_mode_supplies_in_memory_admin_without_clerk(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", False)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    monkeypatch.setattr(po_api, "get_pool", lambda: (_ for _ in ()).throw(AssertionError("Preview must not use Neon")))

    with TestClient(po_api.app, base_url="http://testserver") as client:
        status = client.get("/api/preview-mode")
        assert status.status_code == 200
        assert status.json() == {"enabled": True, "liveData": False}

        me = client.get("/me")
        assert me.status_code == 200
        assert me.json() == {
            "access": True,
            "email": "preview-admin@demo.local",
            "name": "Preview Admin",
            "role": "admin",
            "sections": [
                section
                for section in po_api.SECTIONS_BY_ROLE["admin"]
                if section != "datalake"
            ],
            "previewMode": True,
            "liveData": False,
        }

        # Protected data is available in preview without Clerk, but all values
        # are fixture data and no database pool is created.
        kpis = client.get("/api/kpis")
        assert kpis.status_code == 200
        assert kpis.json()["publishedBy"] == "preview-fixture"
        assert kpis.json()["asOf"] == po_api.PREVIEW_KPI_AS_OF


def test_preview_mode_is_disabled_during_deployment(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", True)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", True)
    monkeypatch.setattr(po_api, "_clerk", None)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        assert client.get("/api/preview-mode").json() == {
            "enabled": False,
            "liveData": False,
        }
        response = client.get("/me")
        assert response.status_code == 503
        assert response.json()["detail"] == "Auth is not configured"


def test_preview_user_management_is_read_only(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", False)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    monkeypatch.setattr(po_api, "get_pool", lambda: (_ for _ in ()).throw(AssertionError("Preview must not use Neon")))

    with TestClient(po_api.app, base_url="http://testserver") as client:
        users = client.get("/users")
        assert users.status_code == 200
        assert users.json() == po_api.PREVIEW_USERS
        access_history = client.get("/users/access-history")
        assert access_history.status_code == 200
        assert access_history.json() == po_api.PREVIEW_ACCESS_HISTORY

        roles = client.get("/roles")
        assert roles.status_code == 200
        assert roles.json() == po_api._role_access_catalog()

        create = client.post(
            "/users",
            json={
                "email": "new.user@colonydisplay.com",
                "name": "New User",
                "role": "viewer",
            },
        )
        assert create.status_code == 403
        assert create.json()["detail"] == "User changes are disabled in preview mode"

        update = client.patch("/users/123", json={"role": "admin"})
        assert update.status_code == 403
        assert update.json()["detail"] == "User changes are disabled in preview mode"


def test_every_preview_read_route_uses_fixtures_without_neon(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", False)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)

    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("Preview must not use the Neon read model")

    monkeypatch.setattr(po_api, "get_pool", unexpected_read)
    monkeypatch.setattr(po_api, "_kpi_read", unexpected_read)

    get_paths = [
        "/recent?limit=2",
        "/health",
        "/parts/DEMO-LED-24",
        "/vendors/DEMO-100",
        "/search?q=LED&mode=or",
        "/summary/DEMO-LED-24",
        "/inventory",
        "/inventory/search?q=acrylic",
        "/inventory/parts/DEMO-ACRYL-12",
        "/inventory/warehouses",
        "/inventory/warehouses/MAIN",
        "/roles",
        "/users",
        "/users/access-history",
        "/api/kpis",
        "/api/kpis/trends",
        f"/api/kpis/SH-01/detail?date={po_api.PREVIEW_KPI_AS_OF}",
        f"/api/kpis/SH-01/detail?month={po_api.PREVIEW_KPI_AS_OF[:7]}",
        "/api/health",
    ]

    with TestClient(po_api.app, base_url="http://testserver") as client:
        for path in get_paths:
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)

        bulk = client.post(
            "/bulk-lookup",
            json={"part_numbers": ["DEMO-LED-24", "DEMO-BRKT-90"]},
        )
        assert bulk.status_code == 200
        assert {row["part_num"] for row in bulk.json()} == {"DEMO-LED-24", "DEMO-BRKT-90"}

        assert client.get("/recent?limit=2").json() == po_api.PREVIEW_PO_ROWS[:2]
        assert client.get("/inventory").json() == po_api.PREVIEW_INVENTORY_ROWS
        assert client.get("/api/kpis").json()["publishedBy"] == "preview-fixture"
        assert client.get("/api/health").json()["database"] == "sample"


def test_preview_disabled_connection_dependency_uses_database_pool(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", False)
    entered = []

    class ConnectionContext:
        def __enter__(self):
            entered.append(True)
            return object()

        def __exit__(self, *_args):
            return False

    class Pool:
        def connection(self):
            return ConnectionContext()

    monkeypatch.setattr(po_api, "get_pool", lambda: Pool())
    request = SimpleNamespace(
        url=SimpleNamespace(hostname="testserver"),
        state=SimpleNamespace(),
    )
    dependency = po_api.get_conn(request)

    assert next(dependency) is not None
    dependency.close()
    assert entered == [True]


def test_valid_session_uses_real_data_while_unsigned_preview_is_enabled(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", False)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    repository_calls = []

    class SignedInClerk:
        def authenticate_request(self, _request, _options):
            return SimpleNamespace(is_signed_in=True, payload={"sub": "employee_test"})

    class Result:
        def fetchall(self):
            return [{"part_num": "REAL-PART", "description": "Repository result"}]

        def fetchone(self):
            return {"rows": 1, "max_order_date": datetime.date(2026, 8, 20)}

    class Connection:
        def execute(self, query, params=()):
            repository_calls.append(("po", query, params))
            return Result()

    class ConnectionContext:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return False

    class Pool:
        def connection(self):
            return ConnectionContext()

    def published_payload(kind, as_of):
        repository_calls.append(("kpi", kind, as_of))
        return {"source": "real-repository", "kind": kind}

    def kpi_read(query, params=()):
        repository_calls.append(("kpi-read", query, params))
        if "v_detail_payload" in query:
            return {"payload": {"source": "real-repository", "metricId": params[0]}}
        if "v_publish_status" in query:
            return {
                "latest_as_of": datetime.date(2026, 8, 20),
                "last_success_at": datetime.datetime(2026, 8, 20, tzinfo=datetime.timezone.utc),
                "failures_7d": 0,
            }
        raise AssertionError(query)

    monkeypatch.setattr(po_api, "_clerk", SignedInClerk())
    monkeypatch.setattr(
        po_api,
        "_clerk_user_info",
        lambda _user_id: {
            "allowed": True,
            "email": "employee@colonydisplay.com",
            "name": "Signed In Employee",
        },
    )
    monkeypatch.setattr(
        po_api,
        "_get_app_user",
        lambda *_args: {"active": True, "role": "viewer"},
    )
    monkeypatch.setattr(po_api, "get_pool", lambda: Pool())
    monkeypatch.setattr(po_api, "_published_payload", published_payload)
    monkeypatch.setattr(po_api, "_kpi_read", kpi_read)
    monkeypatch.setattr(po_api, "_prior_weekday_central", lambda: datetime.date(2026, 8, 20))
    headers = {"Authorization": "Bearer valid-session"}

    with TestClient(po_api.app, base_url="http://testserver") as client:
        recent = client.get("/recent", headers=headers)
        kpis = client.get("/api/kpis", headers=headers)
        trends = client.get("/api/kpis/trends", headers=headers)
        detail = client.get(
            f"/api/kpis/SH-01/detail?date={po_api.PREVIEW_KPI_AS_OF}",
            headers=headers,
        )
        po_health = client.get("/health", headers=headers)
        kpi_health = client.get("/api/health", headers=headers)

    assert recent.status_code == 200
    assert recent.json()[0]["part_num"] == "REAL-PART"
    assert kpis.json() == {"source": "real-repository", "kind": "kpis"}
    assert trends.json() == {"source": "real-repository", "kind": "trends"}
    assert detail.json() == {"source": "real-repository", "metricId": "SH-01"}
    assert po_health.json()["rows"] == 1
    assert kpi_health.json()["database"] == "neon"
    assert [call[0] for call in repository_calls] == [
        "po",
        "kpi",
        "kpi",
        "kpi-read",
        "po",
        "kpi-read",
    ]


def test_preview_mode_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", False)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", True)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        assert client.get("/api/preview-mode").json() == {
            "enabled": False,
            "liveData": False,
        }


def test_ui_version_is_current_and_never_cached(monkeypatch, tmp_path):
    ui_dist = tmp_path / "out"
    ui_dist.mkdir()
    (ui_dist / "ui-version.json").write_text(
        json.dumps({"buildId": "test-build-123"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(po_api, "UI_DIST", ui_dist)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        response = client.get("/api/ui-version")

    assert response.status_code == 200
    assert response.json() == {"buildId": "test-build-123"}
    assert response.headers["cache-control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_ui_version_fails_explicitly_for_invalid_export(monkeypatch, tmp_path):
    ui_dist = tmp_path / "out"
    ui_dist.mkdir()
    (ui_dist / "ui-version.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(po_api, "UI_DIST", ui_dist)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        response = client.get("/api/ui-version")

    assert response.status_code == 503
    assert response.json()["detail"] == "Frontend build version is invalid"


def test_live_preview_reads_repository_in_read_only_transactions(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", True)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    statements = []

    class Result:
        def fetchall(self):
            return [{"part_num": "LIVE-PART", "warehouse_code": "MAIN"}]

        def fetchone(self):
            return {"rows": 1, "max_order_date": datetime.date.today()}

    class Transaction:
        def __enter__(self):
            statements.append("transaction-enter")

        def __exit__(self, *_args):
            statements.append("transaction-exit")

    class Connection:
        def transaction(self):
            return Transaction()

        def execute(self, query, params=()):
            statements.append((query, params))
            return Result()

    class ConnectionContext:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return False

    class Pool:
        def connection(self, **_kwargs):
            return ConnectionContext()

    monkeypatch.setattr(po_api, "get_pool", lambda: Pool())
    monkeypatch.setattr(
        po_api,
        "_published_payload",
        lambda kind, as_of: {"source": "live", "kind": kind, "asOf": as_of},
    )

    with TestClient(po_api.app, base_url="http://testserver") as client:
        status = client.get("/api/preview-mode")
        me = client.get("/me")
        recent = client.get("/recent")
        inventory = client.get("/inventory")
        kpis = client.get("/api/kpis")
        health = client.get("/health")
        users = client.get("/users")
        create = client.post(
            "/users",
            json={"email": "blocked@colonydisplay.com", "role": "viewer"},
        )
        update = client.patch("/users/1", json={"role": "admin"})
        run_script = client.post(
            "/run-script",
            json={"script_id": "sf-epicor-audit"},
        )

    assert status.json() == {"enabled": True, "liveData": True}
    assert me.json()["liveData"] is True
    assert "datalake" in me.json()["sections"]
    assert recent.json()[0]["part_num"] == "LIVE-PART"
    assert inventory.json()[0]["part_num"] == "LIVE-PART"
    assert kpis.json()["source"] == "live"
    assert health.json()["rows"] == 1
    assert users.json() == po_api.PREVIEW_USERS
    assert create.status_code == 403
    assert update.status_code == 403
    assert run_script.status_code == 403
    sql = [item[0] for item in statements if isinstance(item, tuple)]
    assert sql.count("SET TRANSACTION READ ONLY") >= 5
    assert not any(
        query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query in sql
    )


def test_live_preview_rejects_production_external_hosts_and_invalid_tokens(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "PREVIEW_LIVE_DATA_REQUESTED", True)
    monkeypatch.setattr(po_api, "_clerk", None)

    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", True)
    with TestClient(po_api.app, base_url="http://testserver") as client:
        assert client.get("/api/preview-mode").json() == {
            "enabled": False,
            "liveData": False,
        }
        assert client.get("/recent").status_code == 503

    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)
    with TestClient(po_api.app, base_url="https://external.example") as client:
        assert client.get("/api/preview-mode").json() == {
            "enabled": False,
            "liveData": False,
        }
        assert client.get("/recent").status_code == 503

    class RejectingClerk:
        def authenticate_request(self, _request, _options):
            return SimpleNamespace(is_signed_in=False, payload=None)

    monkeypatch.setattr(po_api, "_clerk", RejectingClerk())
    with TestClient(po_api.app, base_url="http://testserver") as client:
        headers = {"Authorization": "Bearer invalid"}
        assert client.get("/recent", headers=headers).status_code == 401
        assert client.get("/health", headers=headers).status_code == 401


def test_preview_html_is_not_cached(monkeypatch):
    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", True)
    monkeypatch.setattr(po_api, "IS_DEPLOYMENT", False)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        for path in ("/", "/admin", "/admin/", "/datalake"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"


def test_admin_page_supports_both_next_export_layouts(monkeypatch, tmp_path):
    ui_dist = tmp_path / "out"
    ui_dist.mkdir()
    monkeypatch.setattr(po_api, "UI_DIST", ui_dist)

    flat_export = ui_dist / "admin.html"
    flat_export.write_text("<html>flat admin</html>", encoding="utf-8")
    with TestClient(po_api.app, base_url="http://testserver") as client:
        assert client.get("/admin").text == "<html>flat admin</html>"

    flat_export.unlink()
    nested_export = ui_dist / "admin" / "index.html"
    nested_export.parent.mkdir()
    nested_export.write_text("<html>nested admin</html>", encoding="utf-8")
    with TestClient(po_api.app, base_url="http://testserver") as client:
        assert client.get("/admin/").text == "<html>nested admin</html>"


def test_admin_page_fails_explicitly_when_export_is_missing(monkeypatch, tmp_path):
    ui_dist = tmp_path / "out"
    ui_dist.mkdir()
    monkeypatch.setattr(po_api, "UI_DIST", ui_dist)

    with TestClient(po_api.app, base_url="http://testserver") as client:
        response = client.get("/admin")

    assert response.status_code == 404
    assert response.json()["detail"] == "Admin page is not built"
