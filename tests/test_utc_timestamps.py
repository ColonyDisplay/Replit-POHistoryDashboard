"""Run-timestamp values sent to Neon (TIMESTAMPTZ, session TimeZone GMT) must
be timezone-aware UTC, never naive local time.

Run: python -m unittest discover -s tests
"""
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bin_inv_sync  # noqa: E402
import po_detail_report  # noqa: E402


def _assert_utc_aware(tc, value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    tc.assertIsNotNone(value.tzinfo, "timestamp is naive")
    tc.assertEqual(value.utcoffset(), timedelta(0), "timestamp is not UTC")


class _RecordingTarget:
    name = "fake"

    def __init__(self):
        self.synced_at = None
        self.run_log_ts = None

    def count(self):
        return 0

    def rows_from_records(self, recs, synced_at):
        self.synced_at = synced_at
        return []

    def upsert(self, rows):
        pass

    def write_run_log(self, synced_at, mode, upserted, total):
        self.run_log_ts = synced_at

    def close(self):
        pass


class BinInvSyncTests(unittest.TestCase):
    def test_sync_passes_utc_aware_synced_at(self):
        target = _RecordingTarget()
        with mock.patch.object(bin_inv_sync, "_make_targets", return_value=[target]), \
             mock.patch.object(bin_inv_sync, "fetch_paged", return_value=iter([[{}]])), \
             mock.patch("builtins.print"):
            bin_inv_sync.sync(auth=None)
        _assert_utc_aware(self, target.synced_at)
        _assert_utc_aware(self, target.run_log_ts)

    def test_neon_http_payloads_carry_utc_offset(self):
        t = bin_inv_sync.NeonHttpTarget.__new__(bin_inv_sync.NeonHttpTarget)
        t._execute = mock.Mock()
        ts = datetime.now(bin_inv_sync.timezone.utc)
        row = t.rows_from_records([{}], ts)[0]
        _assert_utc_aware(self, row[-1])
        t.write_run_log(ts, "incremental", 1, 1)
        _assert_utc_aware(self, t._execute.call_args[0][1][0])


class PoDetailReportTests(unittest.TestCase):
    def test_neon_http_run_log_is_utc(self):
        t = po_detail_report.NeonHttpTarget.__new__(po_detail_report.NeonHttpTarget)
        t._execute = mock.Mock()
        t.write_run_log("incremental", 0, 0, 0, "2026-11-01")
        _assert_utc_aware(self, t._execute.call_args[0][1][0])

    def test_postgres_run_log_is_utc(self):
        t = po_detail_report.PostgresTarget.__new__(po_detail_report.PostgresTarget)
        t.conn = mock.MagicMock()
        cur = t.conn.cursor.return_value.__enter__.return_value
        t.write_run_log("incremental", 0, 0, 0, "2026-11-01")
        _assert_utc_aware(self, cur.execute.call_args[0][1][0])

    def test_sqlite_run_log_is_utc(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(po_detail_report._SQLITE_DDL)
        po_detail_report._write_run_log(conn, "incremental", 0, 0, 0, "2026-11-01")
        _assert_utc_aware(self, conn.execute("SELECT run_timestamp FROM run_log").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
