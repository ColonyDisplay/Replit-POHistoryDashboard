import po_api


def test_pool_checks_connections_before_checkout(monkeypatch):
    captured = {}

    class FakeConnectionPool:
        @staticmethod
        def check_connection(_connection):
            return None

        def __init__(self, conninfo, **kwargs):
            captured["conninfo"] = conninfo
            captured["kwargs"] = kwargs

    monkeypatch.setattr(po_api, "pool", None)
    monkeypatch.setattr(po_api, "DATABASE_URL", "postgresql://example.invalid/app")
    monkeypatch.setattr(po_api, "ConnectionPool", FakeConnectionPool)

    created = po_api.get_pool()

    assert isinstance(created, FakeConnectionPool)
    assert captured["kwargs"]["check"] is FakeConnectionPool.check_connection