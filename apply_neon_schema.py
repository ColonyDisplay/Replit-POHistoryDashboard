"""Apply neon-schema.sql to the Postgres database in DATABASE_URL.

Idempotent (the DDL uses IF NOT EXISTS throughout). Run once when
provisioning Neon, per handoff-powerbi.md "Build Tasks 1. Provision Neon".

Usage:
    $env:DATABASE_URL = "postgresql://...sslmode=require"
    .venv/Scripts/python.exe apply_neon_schema.py
"""
import os
import sys
from pathlib import Path

import psycopg

SCHEMA_FILE = Path(__file__).parent / "neon-schema.sql"


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set.")

    ddl = SCHEMA_FILE.read_text(encoding="utf-8")
    with psycopg.connect(dsn) as conn:
        conn.execute(ddl)
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'po_history' ORDER BY table_name"
        ).fetchall()

    print(f"Applied {SCHEMA_FILE.name}. Tables in schema po_history:")
    for (name,) in tables:
        print(f"  po_history.{name}")


if __name__ == "__main__":
    main()
