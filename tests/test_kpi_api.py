"""Regression coverage for the published Operations KPI API contract."""

import copy
import datetime
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import po_api


METRIC_IDS = [f"OP-{number:02d}" for number in range(1, 44)]
AS_OF = "2026-08-20"


def _summary_payload():
    metrics = [
        {
            "id": metric_id,
            "label": f"Operations metric {number}",
            "unit": "count",
            "daily": number,
            "monthly": number * 10,
            "target": number + 1,
        }
        for number, metric_id in enumerate(METRIC_IDS, start=1)
    ]
    return {
        "asOf": AS_OF,
        "sections": [
            {"id": "operations", "title": "Operations", "metrics": metrics},
        ],
        "publishedBy": "controlled-test-fixture",
    }


def _trends_payload():
    return {
        "asOf": AS_OF,
        "metrics": {
            metric_id: {
                "dailyLast30": [{"date": AS_OF, "value": number}],
                "monthlyTrailing12": [{"month": "2026-08", "value": number * 10}],
            }
            for number, metric_id in enumerate(METRIC_IDS, start=1)
        },
        "publishedBy": "controlled-test-fixture",
    }


DAILY_DETAIL = {
    "metricId": "OP-01",
    "periodType": "date",
    "period": AS_OF,
    "rowCount": 2,
    "totals": {"units": 17, "amount": 123.45},
    "rows": [{"order": "SO-100", "units": 10}, {"order": "SO-101", "units": 7}],
}
MONTHLY_DETAIL = {
    "metricId": "OP-01",
    "periodType": "month",
    "period": "2026-08",
    "rowCount": 1,
    "totals": {"units": 17},
    "rows": [{"month": "2026-08", "units": 17}],
}


class _FakeClerk:
    def authenticate_request(self, request, options):
        is_signed_in = request.headers.get("authorization") == "Bearer test-session"
        return SimpleNamespace(
            is_signed_in=is_signed_in,
            payload={"sub": "user_test"} if is_signed_in else None,
        )


@pytest.fixture
def kpi_api(monkeypatch):
    """Authenticated API client backed by deterministic published payloads."""
    queries = []
    summary = _summary_payload()
    trends = _trends_payload()

    monkeypatch.setattr(po_api, "_clerk", _FakeClerk())
    monkeypatch.setattr(
        po_api,
        "_clerk_user_info",
        lambda _: {"allowed": True, "email": "employee@example.com", "name": "Test Employee"},
    )
    monkeypatch.setattr(
        po_api,
        "_get_app_user",
        lambda *_: {"active": True, "role": "viewer"},
    )

    def published_read(query, params=()):
        queries.append((query, params))
        normalized = " ".join(query.split())
        if "kpi.v_api_payload" in normalized:
            kind = params[0]
            payload = summary if kind == "kpis" else trends
            if len(params) == 2 and params[1] != AS_OF:
                return None
            return {"payload": copy.deepcopy(payload)}
        if "kpi.v_detail_payload" in normalized:
            metric_id, period_type, period = params
            if metric_id != "OP-01":
                return None
            if (period_type, period) == ("date", AS_OF):
                return {"payload": copy.deepcopy(DAILY_DETAIL)}
            if (period_type, period) == ("month", "2026-08"):
                return {"payload": copy.deepcopy(MONTHLY_DETAIL)}
            return None
        if "kpi.v_publish_status" in normalized:
            return {
                "latest_as_of": datetime.date(2026, 8, 20),
                "last_success_at": datetime.datetime(
                    2026, 8, 20, 12, 34, 56, tzinfo=datetime.timezone.utc
                ),
                "failures_7d": 2,
            }
        raise AssertionError(f"Unexpected KPI query: {query}")

    monkeypatch.setattr(po_api, "_kpi_read", published_read)
    return TestClient(po_api.app), queries, summary, trends


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-session"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/kpis",
        "/api/kpis/trends",
        f"/api/kpis/OP-01/detail?date={AS_OF}",
    ],
)
def test_kpi_routes_reject_unauthenticated_requests(kpi_api, path):
    client, _, _, _ = kpi_api

    response = client.get(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_published_summary_and_trends_preserve_the_43_metric_contract(kpi_api, auth_headers):
    client, _, summary, trends = kpi_api

    summary_response = client.get(f"/api/kpis?asOf={AS_OF}", headers=auth_headers)
    trends_response = client.get(f"/api/kpis/trends?asOf={AS_OF}", headers=auth_headers)

    assert summary_response.status_code == 200
    assert summary_response.json() == summary
    metrics = summary_response.json()["sections"][0]["metrics"]
    assert len(metrics) == 43
    assert [metric["id"] for metric in metrics] == METRIC_IDS

    assert trends_response.status_code == 200
    assert trends_response.json() == trends
    assert set(trends_response.json()["metrics"]) == set(METRIC_IDS)
    assert len(trends_response.json()["metrics"]) == 43


def test_daily_and_monthly_detail_preserve_published_payloads(kpi_api, auth_headers):
    client, _, _, _ = kpi_api

    daily_response = client.get(
        f"/api/kpis/OP-01/detail?date={AS_OF}", headers=auth_headers
    )
    monthly_response = client.get(
        "/api/kpis/OP-01/detail?month=2026-08", headers=auth_headers
    )

    assert daily_response.status_code == 200
    assert daily_response.json() == DAILY_DETAIL
    assert monthly_response.status_code == 200
    assert monthly_response.json() == MONTHLY_DETAIL


def test_kpi_routes_use_latest_payload_when_no_as_of_date_is_requested(kpi_api, auth_headers):
    client, queries, summary, trends = kpi_api

    assert client.get("/api/kpis", headers=auth_headers).json() == summary
    assert client.get("/api/kpis/trends", headers=auth_headers).json() == trends

    assert queries[0][1] == ("kpis",)
    assert queries[1][1] == ("trends",)


@pytest.mark.parametrize("path", [
    "/api/kpis", "/api/kpis/trends", "/api/health",
    f"/api/kpis/OP-01/detail?date={AS_OF}",
    "/api/kpis?asOf=2026-08-19",
])
def test_kpi_responses_cannot_be_cached(kpi_api, auth_headers, path):
    client, _, _, _ = kpi_api
    response = client.get(path, headers=auth_headers)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("path", "error", "details"),
    [
        ("/api/kpis?asOf=2026-8-20", "Invalid asOf date", "Use ?asOf=YYYY-MM-DD"),
        ("/api/kpis/trends?asOf=2026-02-30", "Invalid asOf date", "Use ?asOf=YYYY-MM-DD"),
        (f"/api/kpis/invalid/detail?date={AS_OF}", "Invalid metric ID", "Use a published metric ID"),
        ("/api/kpis/OP-01/detail", "Choose one published period", "Provide exactly one of ?date=YYYY-MM-DD or ?month=YYYY-MM"),
        (f"/api/kpis/OP-01/detail?date={AS_OF}&month=2026-08", "Choose one published period", "Provide exactly one of ?date=YYYY-MM-DD or ?month=YYYY-MM"),
        ("/api/kpis/OP-01/detail?date=2026-02-30", "Invalid date", "Use ?date=YYYY-MM-DD"),
        ("/api/kpis/OP-01/detail?month=2026-13", "Invalid month", "Use ?month=YYYY-MM"),
    ],
)
def test_kpi_validation_returns_sanitized_errors(kpi_api, auth_headers, path, error, details):
    client, queries, _, _ = kpi_api

    response = client.get(path, headers=auth_headers)

    assert response.status_code == 400
    assert response.json() == {"error": error, "details": details}
    assert queries == []


def test_kpi_routes_return_not_found_only_for_unpublished_data(kpi_api, auth_headers):
    client, _, _, _ = kpi_api

    response = client.get("/api/kpis?asOf=2026-08-19", headers=auth_headers)
    detail_response = client.get(
        f"/api/kpis/OP-43/detail?date={AS_OF}", headers=auth_headers
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Published KPI data was not found"
    assert detail_response.status_code == 404
    assert detail_response.json()["error"] == "Published KPI detail was not found"


def test_kpi_routes_enforce_the_operations_kpi_role_gate(kpi_api, monkeypatch, auth_headers):
    client, queries, _, _ = kpi_api
    monkeypatch.setattr(po_api, "_get_app_user", lambda *_: {"active": True, "role": "none"})

    response = client.get("/api/kpis", headers=auth_headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "section_forbidden"}
    assert queries == []


def test_public_kpi_health_reports_sanitized_freshness(kpi_api, monkeypatch):
    client, _, _, _ = kpi_api
    monkeypatch.setattr(po_api, "_prior_weekday_central", lambda: datetime.date(2026, 8, 20))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "state": "ok",
        "database": "neon",
        "databaseStatus": "connected",
        "appVersion": "unknown",
        "latestSuccessfulPublish": AS_OF,
        "lastSuccessAt": "2026-08-20T12:34:56+00:00",
        "expectedBusinessDate": AS_OF,
        "failures7d": 2,
    }


def test_public_kpi_health_hides_repository_failures(kpi_api, monkeypatch):
    client, _, _, _ = kpi_api
    monkeypatch.setattr(
        po_api,
        "_kpi_read",
        lambda *_: (_ for _ in ()).throw(
            po_api.KpiRequestError(503, "internal database error", "private detail")
        ),
    )
    monkeypatch.setattr(po_api, "_prior_weekday_central", lambda: datetime.date(2026, 8, 20))

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "state": "error",
        "database": "neon",
        "databaseStatus": "unavailable",
        "appVersion": "unknown",
        "latestSuccessfulPublish": None,
        "lastSuccessAt": None,
        "expectedBusinessDate": AS_OF,
        "failures7d": 0,
    }


def test_kpi_repository_queries_only_approved_read_only_views(kpi_api, auth_headers):
    client, queries, _, _ = kpi_api
    paths = [
        f"/api/kpis?asOf={AS_OF}",
        f"/api/kpis/trends?asOf={AS_OF}",
        f"/api/kpis/OP-01/detail?date={AS_OF}",
        "/api/health",
    ]

    for path in paths:
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 200

    approved_views = {
        "kpi.v_api_payload",
        "kpi.v_detail_payload",
        "kpi.v_publish_status",
    }
    seen_views = set()
    for query, _ in queries:
        normalized = " ".join(query.split())
        assert normalized.upper().startswith("SELECT ")
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CALL|CREATE|ALTER|DROP)\b", normalized, re.I)
        match = re.search(r"\bFROM\s+(kpi\.\w+)\b", normalized, re.I)
        assert match, normalized
        seen_views.add(match.group(1).lower())

    assert seen_views == approved_views


def test_kpi_repository_opens_a_read_only_transaction(monkeypatch):
    statements = []

    class Result:
        def fetchone(self):
            return {"payload": {"safe": True}}

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def execute(self, query, params=()):
            statements.append((query, params))
            return Result()

        def transaction(self):
            return Transaction()

    class ConnectionContext:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_):
            return False

    class Pool:
        def connection(self, timeout):
            assert timeout == 10
            return ConnectionContext()

    monkeypatch.setattr(po_api, "get_pool", lambda: Pool())

    result = po_api._kpi_read("SELECT payload FROM kpi.v_api_payload WHERE kind = %s", ("kpis",))

    assert result == {"payload": {"safe": True}}
    assert statements == [
        ("SET TRANSACTION READ ONLY", ()),
        ("SET LOCAL statement_timeout = '15s'", ()),
        ("SELECT payload FROM kpi.v_api_payload WHERE kind = %s", ("kpis",)),
    ]