"""Regression coverage for company-wide baseline access and admin boundaries."""

import json

import pytest

import po_api


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _ProvisioningConnection:
    def __init__(self, existing_user_count, user=None, fail_audit=False):
        self.existing_user_count = existing_user_count
        self.user = user
        self.fail_audit = fail_audit
        self.audit_params = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        normalized = " ".join(query.split())
        assert normalized.count("%s") == len(params), (
            f"SQL placeholder mismatch: {normalized.count('%s')} placeholders "
            f"for {len(params)} parameters"
        )
        if normalized.startswith(
            "SELECT * FROM po_history.users WHERE lower(email) = %s"
        ):
            return _Result(self.user)
        if "pg_advisory_xact_lock" in normalized:
            return _Result()
        if normalized == "SELECT COUNT(*) AS n FROM po_history.users":
            return _Result({"n": self.existing_user_count})
        if normalized.startswith("INSERT INTO po_history.users"):
            if len(params) == 2:
                email, name = params
                role = "admin"
            else:
                email, name, role = params
            self.user = {
                "id": self.user["id"] if self.user else 42,
                "email": email,
                "name": self.user["name"] if self.user else name,
                "role": role,
                "active": True,
            }
            return _Result(self.user)
        if normalized.startswith("INSERT INTO po_history.user_access_audit"):
            if self.fail_audit:
                raise RuntimeError("audit unavailable")
            self.audit_params.append(params)
            return _Result()
        raise AssertionError(f"Unexpected query: {normalized}")

    def commit(self):
        self.commits += 1


class _ProvisioningPool:
    def __init__(self, connection):
        self._connection = connection

    def connection(self):
        return self._connection


@pytest.mark.parametrize(
    ("existing_user_count", "expected_role", "expected_actor"),
    [
        (0, "admin", "Portal bootstrap"),
        (1, "viewer", "Automatic sign-in provisioning"),
    ],
)
def test_verified_company_signers_are_provisioned(
    monkeypatch, existing_user_count, expected_role, expected_actor
):
    email = f"new-{existing_user_count}@colonydisplay.com"
    connection = _ProvisioningConnection(existing_user_count)
    monkeypatch.setattr(
        po_api, "get_pool", lambda: _ProvisioningPool(connection)
    )
    monkeypatch.setattr(po_api, "ADMIN_EMAILS", set())
    po_api._invalidate_user_cache(email)

    user = po_api._get_app_user(email, "New Employee")

    assert user == {
        "id": 42,
        "email": email,
        "name": "New Employee",
        "role": expected_role,
        "active": True,
    }
    assert connection.commits == 1
    assert len(connection.audit_params) == 1
    audit = connection.audit_params[0]
    assert audit[:7] == (
        "user_created",
        "system",
        None,
        None,
        expected_actor,
        42,
        email,
    )
    assert audit[7] is None
    assert json.loads(audit[8]) == {
        "role": expected_role,
        "active": True,
    }
    po_api._invalidate_user_cache(email)

@pytest.mark.parametrize(
    ("user", "expected_action", "expected_previous"),
    [
        (
            {
                "id": 7,
                "email": "owner@colonydisplay.com",
                "name": "Owner",
                "role": "viewer",
                "active": True,
            },
            "role_changed",
            {"role": "viewer", "active": True},
        ),
        (
            {
                "id": 7,
                "email": "owner@colonydisplay.com",
                "name": "Owner",
                "role": "admin",
                "active": False,
            },
            "activated",
            {"role": "admin", "active": False},
        ),
    ],
)
def test_emergency_admin_enforcement_is_audited(
    monkeypatch, user, expected_action, expected_previous
):
    connection = _ProvisioningConnection(existing_user_count=2, user=user.copy())
    monkeypatch.setattr(
        po_api, "get_pool", lambda: _ProvisioningPool(connection)
    )
    monkeypatch.setattr(po_api, "ADMIN_EMAILS", {user["email"]})
    po_api._invalidate_user_cache(user["email"])

    result = po_api._get_app_user(user["email"], user["name"])

    assert result["role"] == "admin"
    assert result["active"] is True
    assert connection.commits == 1
    audit = connection.audit_params[0]
    assert audit[0] == expected_action
    assert audit[1:5] == (
        "system",
        None,
        None,
        "Emergency admin policy",
    )
    assert json.loads(audit[7]) == expected_previous
    assert json.loads(audit[8]) == {"role": "admin", "active": True}
    po_api._invalidate_user_cache(user["email"])
@pytest.mark.parametrize("role", po_api.ROLES)
def test_all_defined_roles_receive_baseline_dashboard_access(role):
    sections = set(po_api.SECTIONS_BY_ROLE[role])

    assert set(po_api.BASELINE_SECTIONS) <= sections
    assert ("users" in sections) is (role == "admin")
    assert ("datalake" in sections) is (role == "admin")


def test_role_access_catalog_is_derived_from_backend_permissions():
    catalog = po_api._role_access_catalog()
    baseline_ids = [
        section["id"] for section in catalog["baselineSections"]
    ]
    roles = {role["id"]: role for role in catalog["roles"]}

    assert catalog["defaultRole"] == po_api.DEFAULT_ROLE == "viewer"
    assert catalog["defaultRole"] in po_api.ROLES
    assert baseline_ids == po_api.BASELINE_SECTIONS
    assert list(roles) == list(po_api.ROLES)

    for role_id, role in roles.items():
        section_ids = [section["id"] for section in role["sections"]]
        admin_only_ids = [
            section["id"] for section in role["adminOnlySections"]
        ]

        assert role["label"]
        assert section_ids == po_api.SECTIONS_BY_ROLE[role_id]
        assert admin_only_ids == [
            section
            for section in po_api.SECTIONS_BY_ROLE[role_id]
            if section not in po_api.BASELINE_SECTIONS
        ]
        assert all(section["label"] for section in role["sections"])

@pytest.mark.parametrize("emergency", [False, True])
def test_automatic_access_change_rolls_back_when_audit_fails(
    monkeypatch, emergency
):
    email = (
        "owner@colonydisplay.com"
        if emergency
        else "new.employee@colonydisplay.com"
    )
    user = (
        {
            "id": 7,
            "email": email,
            "name": "Owner",
            "role": "viewer",
            "active": True,
        }
        if emergency
        else None
    )
    connection = _ProvisioningConnection(
        existing_user_count=2,
        user=user,
        fail_audit=True,
    )
    monkeypatch.setattr(
        po_api, "get_pool", lambda: _ProvisioningPool(connection)
    )
    monkeypatch.setattr(po_api, "ADMIN_EMAILS", {email} if emergency else set())
    po_api._invalidate_user_cache(email)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        po_api._get_app_user(email, "Employee")

    assert connection.commits == 0
    assert email not in po_api._app_user_cache
