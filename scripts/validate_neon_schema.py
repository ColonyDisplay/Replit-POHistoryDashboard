#!/usr/bin/env python3
"""Read-only release check for the external Neon schema and runtime grants."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

import psycopg


SCHEMA = "po_history"
SCHEMA_SQL_PATH = Path(__file__).resolve().parents[1] / "neon-schema.sql"

_TYPE_NAMES = {
    "BIGSERIAL": "bigint",
    "BIGINT": "bigint",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "INTEGER": "integer",
    "JSONB": "jsonb",
    "NUMERIC": "numeric",
    "SERIAL": "integer",
    "TEXT": "text",
    "TIMESTAMPTZ": "timestamp with time zone",
}


def _split_definitions(body: str) -> list[str]:
    definitions = []
    start = depth = 0
    for position, character in enumerate(body):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            definitions.append(body[start:position].strip())
            start = position + 1
    definitions.append(body[start:].strip())
    return [definition for definition in definitions if definition]


def _table_statements(sql: str) -> list[tuple[str, str]]:
    statements = []
    pattern = re.compile(r"\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\(", re.I)
    for match in pattern.finditer(sql):
        depth = 1
        position = match.end()
        while position < len(sql) and depth:
            depth += (sql[position] == "(") - (sql[position] == ")")
            position += 1
        if depth:
            raise ValueError(f"Unclosed CREATE TABLE statement for {match.group(1)}")
        statements.append((match.group(1), sql[match.end() : position - 1]))
    return statements


def parse_schema_contract(sql: str) -> tuple[
    dict[str, dict[str, tuple[str, bool]]],
    dict[str, dict[str, tuple[str, ...]]],
    dict[str, str],
    set[str],
]:
    """Derive the release contract from the canonical schema SQL."""
    sql = re.sub(r"--[^\n]*", "", sql)
    columns: dict[str, dict[str, tuple[str, bool]]] = {}
    keys: dict[str, dict[str, tuple[str, ...]]] = {}
    sequences: set[str] = set()

    for table, body in _table_statements(sql):
        table_columns: dict[str, tuple[str, bool]] = {}
        table_keys: dict[str, tuple[str, ...]] = {}
        primary_columns: set[str] = set()

        for definition in _split_definitions(body):
            constraint = re.match(
                r"(PRIMARY\s+KEY|UNIQUE)\s*\(([^)]+)\)", definition, re.I
            )
            if constraint:
                key_type = re.sub(r"\s+", " ", constraint.group(1).upper())
                key_columns = tuple(
                    column.strip() for column in constraint.group(2).split(",")
                )
                table_keys[key_type] = key_columns
                if key_type == "PRIMARY KEY":
                    primary_columns.update(key_columns)
                continue
            if definition.upper().startswith(("CHECK ", "CONSTRAINT ")):
                continue

            column_match = re.match(r"(\w+)\s+(\w+)(.*)", definition, re.S)
            if not column_match:
                raise ValueError(
                    f"Unsupported column definition in {table}: {definition}"
                )
            column, sql_type, modifiers = column_match.groups()
            normalized_type = _TYPE_NAMES.get(sql_type.upper())
            if normalized_type is None:
                raise ValueError(f"Unsupported type {sql_type} for {table}.{column}")
            is_nullable = not bool(re.search(r"\bNOT\s+NULL\b", modifiers, re.I))
            table_columns[column] = (normalized_type, is_nullable)
            if sql_type.upper() in {"SERIAL", "BIGSERIAL"}:
                sequences.add(f"{table}_{column}_seq")
            if re.search(r"\bPRIMARY\s+KEY\b", modifiers, re.I):
                table_keys["PRIMARY KEY"] = (column,)
                primary_columns.add(column)
            if re.search(r"\bUNIQUE\b", modifiers, re.I):
                table_keys["UNIQUE"] = (column,)

        for column in primary_columns:
            data_type, _ = table_columns[column]
            table_columns[column] = (data_type, False)
        columns[table] = table_columns
        if table_keys:
            keys[table] = table_keys

    indexes = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"\bCREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+ON\s+(\w+)\s*\(",
            sql,
            re.I,
        )
    }
    for table, table_keys in keys.items():
        if "PRIMARY KEY" in table_keys:
            indexes[f"{table}_pkey"] = table
        if unique_columns := table_keys.get("UNIQUE"):
            indexes[f"{table}_{'_'.join(unique_columns)}_key"] = table
    if not columns:
        raise ValueError("neon-schema.sql contains no CREATE TABLE statements")
    return columns, keys, indexes, sequences


REQUIRED_COLUMNS, REQUIRED_KEYS, REQUIRED_INDEXES, _SCHEMA_SEQUENCES = (
    parse_schema_contract(SCHEMA_SQL_PATH.read_text())
)
REQUIRED_TABLES = set(REQUIRED_COLUMNS)

REQUIRED_TABLE_PRIVILEGES = {
    "po_detail": ("SELECT",),
    "run_log": ("SELECT",),
    "bin_inventory": ("SELECT",),
    "inv_run_log": ("SELECT",),
    "users": ("SELECT", "INSERT", "UPDATE"),
    "user_access_audit": ("SELECT", "INSERT"),
}

REQUIRED_SEQUENCE_PRIVILEGES = {
    "users_id_seq": ("USAGE", "SELECT"),
    "user_access_audit_id_seq": ("USAGE", "SELECT"),
}

REQUIRED_DEFAULTS = {
    ("users", "id"): "nextval('po_history.users_id_seq'::regclass)",
    ("users", "role"): "'viewer'::text",
    ("users", "active"): "true",
    ("users", "created_at"): "now()",
    ("users", "updated_at"): "now()",
    ("user_access_audit", "id"): (
        "nextval('po_history.user_access_audit_id_seq'::regclass)"
    ),
    ("user_access_audit", "changed_at"): "now()",
}

REQUIRED_SEQUENCE_OWNERS = {
    "users_id_seq": ("users", "id"),
    "user_access_audit_id_seq": ("user_access_audit", "id"),
}


def _missing_privileges(
    conn,
    object_kind: str,
    object_name: str,
    privileges: Iterable[str],
) -> list[str]:
    qualified_name = f"{SCHEMA}.{object_name}"
    check_function = {
        "table": "has_table_privilege",
        "sequence": "has_sequence_privilege",
    }[object_kind]
    missing = []
    for privilege in privileges:
        row = conn.execute(
            f"SELECT {check_function}(current_user, %s, %s)",
            (qualified_name, privilege),
        ).fetchone()
        if not row[0]:
            missing.append(privilege)
    return missing


def validate(conn) -> list[str]:
    """Return actionable contract violations without changing the database."""
    failures: list[str] = []

    schema_row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)",
        (SCHEMA,),
    ).fetchone()
    if not schema_row[0]:
        return [
            f"Missing schema {SCHEMA}. Apply neon-schema.sql as the schema owner, "
            "then grant only the runtime privileges listed below."
        ]

    usage_row = conn.execute(
        "SELECT has_schema_privilege(current_user, %s, 'USAGE')",
        (SCHEMA,),
    ).fetchone()
    if not usage_row[0]:
        failures.append(
            f"Runtime role lacks USAGE on schema {SCHEMA}. "
            f"Remediation: GRANT USAGE ON SCHEMA {SCHEMA} TO <runtime_role>;"
        )

    table_rows = conn.execute(
        """
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
        """,
        (SCHEMA,),
    ).fetchall()
    existing_tables = {row[0] for row in table_rows}

    for table in REQUIRED_TABLES:
        if table not in existing_tables:
            failures.append(
                f"Missing table {SCHEMA}.{table}. "
                "Remediation: apply the matching CREATE TABLE statement from neon-schema.sql."
            )

    for table, privileges in REQUIRED_TABLE_PRIVILEGES.items():
        if table not in existing_tables:
            continue
        missing = _missing_privileges(conn, "table", table, privileges)
        if missing:
            privilege_list = ", ".join(missing)
            failures.append(
                f"Runtime role lacks {privilege_list} on {SCHEMA}.{table}. "
                f"Remediation: GRANT {privilege_list} ON TABLE "
                f"{SCHEMA}.{table} TO <runtime_role>;"
            )

    column_rows = conn.execute(
        """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
               NOT a.attnotnull AS is_nullable
        FROM pg_attribute AS a
        JOIN pg_class AS c ON c.oid = a.attrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND a.attnum > 0
          AND NOT a.attisdropped
        """,
        (SCHEMA,),
    ).fetchall()
    existing_columns = {
        (table, column): (data_type, is_nullable)
        for table, column, data_type, is_nullable in column_rows
    }
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in existing_tables:
            continue
        for column, expected in columns.items():
            actual = existing_columns.get((table, column))
            qualified_column = f"{SCHEMA}.{table}.{column}"
            if actual is None:
                failures.append(
                    f"Missing column {qualified_column}. Remediation: as the schema "
                    "owner, apply the matching column definition from neon-schema.sql; "
                    "this validation made no changes."
                )
                continue
            if actual[0] != expected[0]:
                failures.append(
                    f"Incompatible type for {qualified_column}: expected "
                    f"{expected[0]}, found {actual[0]}. Remediation: as the schema "
                    "owner, reconcile existing data and apply the matching type from "
                    "neon-schema.sql; this validation made no changes."
                )
            if actual[1] != expected[1]:
                expected_nullability = "nullable" if expected[1] else "NOT NULL"
                actual_nullability = "nullable" if actual[1] else "NOT NULL"
                failures.append(
                    f"Incompatible nullability for {qualified_column}: expected "
                    f"{expected_nullability}, found {actual_nullability}. Remediation: "
                    "as the schema owner, reconcile existing data and apply the matching "
                    "nullability from neon-schema.sql; this validation made no changes."
                )

    default_rows = conn.execute(
        """
        SELECT c.relname, a.attname, pg_get_expr(ad.adbin, ad.adrelid)
        FROM pg_attribute AS a
        JOIN pg_class AS c ON c.oid = a.attrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef AS ad
          ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND a.attnum > 0
          AND NOT a.attisdropped
        """,
        (SCHEMA,),
    ).fetchall()
    existing_defaults = {
        (table, column): default
        for table, column, default in default_rows
    }
    for (table, column), expected_default in REQUIRED_DEFAULTS.items():
        if table not in existing_tables or (table, column) not in existing_columns:
            continue
        actual_default = existing_defaults.get((table, column))
        if actual_default != expected_default:
            found = actual_default if actual_default is not None else "none"
            failures.append(
                f"Incompatible default for {SCHEMA}.{table}.{column}: expected "
                f"{expected_default}, found {found}. Remediation: as the schema owner, "
                "apply the matching DEFAULT from neon-schema.sql; this validation made "
                "no changes."
            )

    key_rows = conn.execute(
        """
        SELECT c.relname, con.contype,
               array_agg(a.attname ORDER BY key_column.ordinality)
        FROM pg_constraint AS con
        JOIN pg_class AS c ON c.oid = con.conrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL unnest(con.conkey)
            WITH ORDINALITY AS key_column(attnum, ordinality)
        JOIN pg_attribute AS a
          ON a.attrelid = c.oid AND a.attnum = key_column.attnum
        WHERE n.nspname = %s AND con.contype IN ('p', 'u')
        GROUP BY c.relname, con.oid, con.contype
        """,
        (SCHEMA,),
    ).fetchall()
    existing_keys = {
        (table, "PRIMARY KEY" if key_type == "p" else "UNIQUE"): tuple(columns)
        for table, key_type, columns in key_rows
    }
    for table, keys in REQUIRED_KEYS.items():
        if table not in existing_tables:
            continue
        for key_type, expected_columns in keys.items():
            actual_columns = existing_keys.get((table, key_type))
            if actual_columns != expected_columns:
                found = (
                    f"({', '.join(actual_columns)})"
                    if actual_columns is not None
                    else "none"
                )
                failures.append(
                    f"Incompatible {key_type} on {SCHEMA}.{table}: expected "
                    f"({', '.join(expected_columns)}), found {found}. Remediation: "
                    "as the schema owner, reconcile duplicate/null data and apply the "
                    "matching constraint from neon-schema.sql; this validation made no changes."
                )

    index_rows = conn.execute(
        """
        SELECT indexname, tablename
        FROM pg_indexes
        WHERE schemaname = %s
        """,
        (SCHEMA,),
    ).fetchall()
    existing_indexes = {row[0]: row[1] for row in index_rows}
    for index, table in REQUIRED_INDEXES.items():
        actual_table = existing_indexes.get(index)
        if actual_table != table:
            detail = (
                f" (found on {SCHEMA}.{actual_table})"
                if actual_table is not None
                else ""
            )
            failures.append(
                f"Missing index {SCHEMA}.{index} on {SCHEMA}.{table}{detail}. "
                "Remediation: apply the matching CREATE INDEX statement from neon-schema.sql."
            )

    sequence_rows = conn.execute(
        """
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind = 'S'
        """,
        (SCHEMA,),
    ).fetchall()
    existing_sequences = {row[0] for row in sequence_rows}
    for sequence, privileges in REQUIRED_SEQUENCE_PRIVILEGES.items():
        if sequence not in existing_sequences:
            failures.append(
                f"Missing sequence {SCHEMA}.{sequence}. "
                "Remediation: apply the user_access_audit table definition from neon-schema.sql."
            )
            continue
        missing = _missing_privileges(conn, "sequence", sequence, privileges)
        if missing:
            privilege_list = ", ".join(missing)
            failures.append(
                f"Runtime role lacks {privilege_list} on {SCHEMA}.{sequence}. "
                f"Remediation: GRANT {privilege_list} ON SEQUENCE "
                f"{SCHEMA}.{sequence} TO <runtime_role>;"
            )

    ownership_rows = conn.execute(
        """
        SELECT sequence.relname, owner_table.relname, owner_column.attname
        FROM pg_class AS sequence
        JOIN pg_namespace AS sequence_namespace
          ON sequence_namespace.oid = sequence.relnamespace
        LEFT JOIN pg_depend AS dependency
          ON dependency.classid = 'pg_class'::regclass
         AND dependency.objid = sequence.oid
         AND dependency.objsubid = 0
         AND dependency.refclassid = 'pg_class'::regclass
         AND dependency.deptype IN ('a', 'i')
        LEFT JOIN pg_class AS owner_table
          ON owner_table.oid = dependency.refobjid
        LEFT JOIN pg_attribute AS owner_column
          ON owner_column.attrelid = dependency.refobjid
         AND owner_column.attnum = dependency.refobjsubid
        WHERE sequence_namespace.nspname = %s
          AND sequence.relkind = 'S'
        """,
        (SCHEMA,),
    ).fetchall()
    existing_owners = {
        sequence: (table, column)
        for sequence, table, column in ownership_rows
    }
    for sequence, expected_owner in REQUIRED_SEQUENCE_OWNERS.items():
        if sequence not in existing_sequences:
            continue
        actual_owner = existing_owners.get(sequence)
        if actual_owner != expected_owner:
            found = (
                f"{SCHEMA}.{actual_owner[0]}.{actual_owner[1]}"
                if actual_owner and all(actual_owner)
                else "none"
            )
            failures.append(
                f"Incompatible owner for {SCHEMA}.{sequence}: expected "
                f"{SCHEMA}.{expected_owner[0]}.{expected_owner[1]}, found {found}. "
                "Remediation: as the schema owner, apply the matching SEQUENCE OWNED BY "
                "linkage from neon-schema.sql; this validation made no changes."
            )

    for sequence, (table, column) in REQUIRED_SEQUENCE_OWNERS.items():
        if (
            sequence not in existing_sequences
            or table not in existing_tables
            or (table, column) not in existing_columns
        ):
            continue
        max_id, last_value, is_called = conn.execute(
            f"""
            SELECT (SELECT MAX({column}) FROM {SCHEMA}.{table}) AS max_id,
                   last_value,
                   is_called
            FROM {SCHEMA}.{sequence}
            """
        ).fetchone()
        if max_id is None:
            continue
        next_value = last_value + 1 if is_called else last_value
        if next_value <= max_id:
            failures.append(
                f"Sequence {SCHEMA}.{sequence} is behind {SCHEMA}.{table}.{column}: "
                f"next value is {next_value}, but the maximum stored ID is {max_id}. "
                "Remediation: as the schema owner, run "
                f"SELECT setval('{SCHEMA}.{sequence}', "
                f"(SELECT MAX({column}) FROM {SCHEMA}.{table}), true); "
                "this validation made no changes."
            )

    return failures


def main() -> int:
    database_url = os.environ.get("NEON_DATABASE_URL", "")
    if not database_url:
        print(
            "Neon schema validation failed: NEON_DATABASE_URL is not configured.",
            file=sys.stderr,
        )
        return 1

    try:
        with psycopg.connect(
            database_url,
            sslmode="require",
            dbname=os.environ.get("NEON_DATABASE", "neondb"),
        ) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                failures = validate(conn)
    except psycopg.Error as exc:
        print(
            f"Neon schema validation failed: could not inspect {SCHEMA} "
            f"as the configured runtime role ({exc.__class__.__name__}).",
            file=sys.stderr,
        )
        return 1

    if failures:
        print("Neon schema validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "No changes were made. Apply only the listed remediation as a "
            "database owner, then rerun this validation.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Neon schema validation passed: {len(REQUIRED_TABLE_PRIVILEGES)} tables, "
        f"{sum(len(columns) for columns in REQUIRED_COLUMNS.values())} columns, "
        f"{len(REQUIRED_INDEXES)} indexes, critical keys, and runtime grants are present."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())