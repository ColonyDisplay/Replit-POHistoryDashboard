"""Regression coverage for the administrator access-change audit trail."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import po_api


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _AuditConnection:
    def __init__(self, target=None, updated=None, history=None):
        self.target = target
        self.updated = updated
        self.history = history or []
        self.statements = []
        self.commits = 0

    def execute(self, query, params=()):
        normalized = " ".join(query.split())
        assert normalized.count("%s") == len(params), (
            f"SQL placeholder mismatch: {normalized.count('%s')} placeholders "
            f"for {len(params)} parameters"
        )
        self.statements.append((normalized, params))
        if "pg_advisory_xact_lock" in normalized:
            return _Result()
        if normalized.startswith("SELECT * FROM po_history.users WHERE id"):
            return _Result(row=self.target)
        if normalized.startswith("SELECT id FROM po_history.users WHERE lower(email)"):
            return _Result(row=None)
        if normalized.startswith("SELECT COUNT(*) AS n FROM po_history.users"):
            return _Result(row={"n": 2})
        if normalized.startswith("INSERT INTO po_history.users"):
            return _Result(row=self.updated)
        if normalized.startswith("UPDATE po_history.users"):
            return _Result(row=self.updated)
        if normalized.startswith("INSERT INTO po_history.user_access_audit"):
            return _Result()
        if "FROM po_history.user_access_audit" in normalized:
            return _Result(rows=self.history)
        raise AssertionError(f"Unexpected query: {normalized}")

    def commit(self):
        self.commits += 1


def _request(email="admin@colonydisplay.com"):
    return SimpleNamespace(state=SimpleNamespace(user_email=email, preview_admin=False))


def _audit_params(connection):
    return next(
        params
        for query, params in connection.statements
        if query.startswith("INSERT INTO po_history.user_access_audit")
    )


def test_user_creation_and_audit_record_commit_together(monkeypatch):
    created = {
        "id": 12,
        "email": "new.user@colonydisplay.com",
        "name": "New User",
        "role": "viewer",
        "active": True,
    }
    connection = _AuditConnection(updated=created)
    invalidated = []
    monkeypatch.setattr(po_api, "_invalidate_user_cache", invalidated.append)

    result = po_api.create_user(
        po_api.CreateUserRequest(
            email=created["email"],
            name=created["name"],
            role=created["role"],
        ),
        _request(),
        connection,
    )

    assert result == created
    assert connection.commits == 1
    assert invalidated == [created["email"]]
    params = _audit_params(connection)
    assert params[:7] == (
        "user_created",
        "admin",
        "admin@colonydisplay.com",
        "admin@colonydisplay.com",
        "admin@colonydisplay.com",
        12,
        created["email"],
    )
    assert params[7] is None
    assert json.loads(params[8]) == {"role": "viewer", "active": True}


def test_audit_failure_prevents_user_change_commit_and_cache_refresh(monkeypatch):
    created = {
        "id": 12,
        "email": "new.user@colonydisplay.com",
        "name": "New User",
        "role": "viewer",
        "active": True,
    }
    connection = _AuditConnection(updated=created)
    original_execute = connection.execute

    def fail_audit(query, params=()):
        if "INSERT INTO po_history.user_access_audit" in query:
            raise RuntimeError("audit unavailable")
        return original_execute(query, params)

    connection.execute = fail_audit
    invalidated = []
    monkeypatch.setattr(po_api, "_invalidate_user_cache", invalidated.append)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        po_api.create_user(
            po_api.CreateUserRequest(
                email=created["email"],
                name=created["name"],
                role=created["role"],
            ),
            _request(),
            connection,
        )

    assert connection.commits == 0
    assert invalidated == []


@pytest.mark.parametrize(
    ("patch", "updated_role", "updated_active", "expected_action"),
    [
        ({"role": "purchasing"}, "purchasing", True, "role_changed"),
        ({"active": False}, "viewer", False, "deactivated"),
        ({"active": True}, "viewer", True, "activated"),
        (
            {"role": "warehouse", "active": False},
            "warehouse",
            False,
            "access_changed",
        ),
    ],
)
def test_access_updates_record_prior_and_resulting_state(
    monkeypatch, patch, updated_role, updated_active, expected_action
):
    original_active = False if expected_action == "activated" else True
    original = {
        "id": 8,
        "email": "employee@colonydisplay.com",
        "name": "Employee",
        "role": "viewer",
        "active": original_active,
    }
    updated = {
        **original,
        "role": updated_role,
        "active": updated_active,
    }
    connection = _AuditConnection(target=original, updated=updated)
    monkeypatch.setattr(po_api, "_invalidate_user_cache", lambda *_: None)

    result = po_api.update_user(
        original["id"],
        po_api.UpdateUserRequest(**patch),
        _request(),
        connection,
    )

    assert result == updated
    assert connection.commits == 1
    params = _audit_params(connection)
    assert params[0] == expected_action
    assert json.loads(params[7]) == {
        "role": original["role"],
        "active": original["active"],
    }
    assert json.loads(params[8]) == {
        "role": updated_role,
        "active": updated_active,
    }


def test_name_only_update_does_not_create_access_audit(monkeypatch):
    original = {
        "id": 8,
        "email": "employee@colonydisplay.com",
        "name": "Old Name",
        "role": "viewer",
        "active": True,
    }
    updated = {**original, "name": "New Name"}
    connection = _AuditConnection(target=original, updated=updated)
    monkeypatch.setattr(po_api, "_invalidate_user_cache", lambda *_: None)

    po_api.update_user(
        original["id"],
        po_api.UpdateUserRequest(name="New Name"),
        _request(),
        connection,
    )

    assert connection.commits == 1
    assert not any(
        query.startswith("INSERT INTO po_history.user_access_audit")
        for query, _ in connection.statements
    )


def test_access_history_is_newest_first_and_limited():
    history = [{"id": 3, "action": "role_changed"}]
    connection = _AuditConnection(history=history)

    result = po_api.list_user_access_history(_request(), limit=25, conn=connection)

    assert result == history
    query, params = connection.statements[-1]
    assert "ORDER BY changed_at DESC, id DESC" in query
    assert params == (25,)


def test_non_admin_cannot_read_access_history(monkeypatch):
    class _FakeClerk:
        def authenticate_request(self, _request, _options):
            return SimpleNamespace(is_signed_in=True, payload={"sub": "viewer_test"})

    monkeypatch.setattr(po_api, "PREVIEW_ADMIN_REQUESTED", False)
    monkeypatch.setattr(po_api, "_clerk", _FakeClerk())
    monkeypatch.setattr(
        po_api,
        "_clerk_user_info",
        lambda _: {
            "allowed": True,
            "email": "viewer@colonydisplay.com",
            "name": "Viewer",
        },
    )
    monkeypatch.setattr(
        po_api,
        "_get_app_user",
        lambda *_: {"active": True, "role": "viewer"},
    )
    monkeypatch.setattr(
        po_api,
        "get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("Forbidden route must not query Neon")),
    )

    with TestClient(po_api.app, base_url="http://testserver") as client:
        response = client.get(
            "/users/access-history",
            headers={"Authorization": "Bearer valid-session"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "section_forbidden"}