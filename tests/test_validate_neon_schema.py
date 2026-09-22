from scripts import validate_neon_schema


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(
        self,
        *,
        schema=True,
        schema_usage=True,
        tables=None,
        indexes=None,
        sequences=None,
        columns=None,
        keys=None,
        defaults=None,
        sequence_owners=None,
        sequence_states=None,
        denied=None,
    ):
        self.schema = schema
        self.schema_usage = schema_usage
        self.tables = tables or set(validate_neon_schema.REQUIRED_TABLE_PRIVILEGES)
        self.indexes = indexes or dict(validate_neon_schema.REQUIRED_INDEXES)
        self.sequences = sequences or set(
            validate_neon_schema.REQUIRED_SEQUENCE_PRIVILEGES
        )
        self.columns = columns or {
            (table, column): definition
            for table, columns in validate_neon_schema.REQUIRED_COLUMNS.items()
            for column, definition in columns.items()
        }
        self.keys = keys or {
            (table, key_type): columns
            for table, keys in validate_neon_schema.REQUIRED_KEYS.items()
            for key_type, columns in keys.items()
        }
        self.defaults = (
            dict(validate_neon_schema.REQUIRED_DEFAULTS)
            if defaults is None
            else defaults
        )
        self.sequence_owners = (
            dict(validate_neon_schema.REQUIRED_SEQUENCE_OWNERS)
            if sequence_owners is None
            else sequence_owners
        )
        self.sequence_states = (
            {
                "users_id_seq": (7, 7, True),
                "user_access_audit_id_seq": (12, 12, True),
            }
            if sequence_states is None
            else sequence_states
        )
        self.denied = denied or set()
        self.queries = []

    def execute(self, query, params=()):
        normalized = " ".join(query.split())
        self.queries.append((normalized, params))
        if "FROM pg_namespace WHERE" in normalized:
            return FakeResult([(self.schema,)])
        if "has_schema_privilege" in normalized:
            return FakeResult([(self.schema_usage,)])
        if "FROM pg_constraint AS con" in normalized:
            return FakeResult(
                [
                    (
                        table,
                        "p" if key_type == "PRIMARY KEY" else "u",
                        list(columns),
                    )
                    for (table, key_type), columns in self.keys.items()
                ]
            )
        if "LEFT JOIN pg_attrdef AS ad" in normalized:
            return FakeResult(
                [
                    (table, column, self.defaults.get((table, column)))
                    for table, column in self.columns
                ]
            )
        if "LEFT JOIN pg_depend AS dependency" in normalized:
            return FakeResult(
                [
                    (sequence, *self.sequence_owners.get(sequence, (None, None)))
                    for sequence in self.sequences
                ]
            )
        if "AS max_id" in normalized:
            sequence = normalized.rsplit("FROM po_history.", 1)[1]
            return FakeResult([self.sequence_states[sequence]])
        if "FROM pg_attribute AS a" in normalized:
            return FakeResult(
                [
                    (table, column, definition[0], definition[1])
                    for (table, column), definition in self.columns.items()
                ]
            )
        if "c.relkind IN ('r', 'p')" in normalized:
            return FakeResult([(name,) for name in self.tables])
        if "FROM pg_indexes" in normalized:
            return FakeResult(list(self.indexes.items()))
        if "c.relkind = 'S'" in normalized:
            return FakeResult([(name,) for name in self.sequences])
        if "has_table_privilege" in normalized:
            object_name, privilege = params
            return FakeResult([((object_name, privilege) not in self.denied,)])
        if "has_sequence_privilege" in normalized:
            object_name, privilege = params
            return FakeResult([((object_name, privilege) not in self.denied,)])
        raise AssertionError(f"Unexpected query: {normalized}")


def test_canonical_sql_drives_the_structural_contract():
    sql = validate_neon_schema.SCHEMA_SQL_PATH.read_text()

    columns, keys, indexes, sequences = validate_neon_schema.parse_schema_contract(sql)

    assert columns == validate_neon_schema.REQUIRED_COLUMNS
    assert keys == validate_neon_schema.REQUIRED_KEYS
    assert indexes == validate_neon_schema.REQUIRED_INDEXES
    assert sequences == set(validate_neon_schema.REQUIRED_SEQUENCE_PRIVILEGES)


def test_schema_edit_changes_validator_expectations():
    sql = validate_neon_schema.SCHEMA_SQL_PATH.read_text()
    changed_sql = sql.replace(
        "max_order_date  DATE",
        "max_order_date  TEXT NOT NULL",
        1,
    )

    columns, _, _, _ = validate_neon_schema.parse_schema_contract(changed_sql)

    assert columns["run_log"]["max_order_date"] == ("text", False)


def test_unsupported_schema_type_fails_contract_loading():
    sql = validate_neon_schema.SCHEMA_SQL_PATH.read_text()
    changed_sql = sql.replace("max_order_date  DATE", "max_order_date  XML", 1)

    try:
        validate_neon_schema.parse_schema_contract(changed_sql)
    except ValueError as exc:
        assert str(exc) == "Unsupported type XML for run_log.max_order_date"
    else:
        raise AssertionError("Unsupported canonical SQL must fail the release contract")


def test_validation_passes_for_complete_contract():
    conn = FakeConnection()

    assert validate_neon_schema.validate(conn) == []
    assert all(
        not query.startswith(("CREATE", "ALTER", "GRANT", "REVOKE"))
        for query, _ in conn.queries
    )


def test_validation_reports_missing_objects_with_remediation():
    conn = FakeConnection(
        tables={"po_detail"},
        indexes={"idx_part_num": "po_detail"},
        sequences={"user_access_audit_id_seq"},
    )

    failures = validate_neon_schema.validate(conn)

    assert any(
        "Missing table po_history.user_access_audit" in failure
        and "neon-schema.sql" in failure
        for failure in failures
    )
    assert any(
        "Missing index po_history.idx_user_access_audit_changed_at" in failure
        and "CREATE INDEX" in failure
        for failure in failures
    )


def test_validation_reports_only_required_missing_grants():
    conn = FakeConnection(
        schema_usage=False,
        denied={
            ("po_history.users", "UPDATE"),
            ("po_history.user_access_audit_id_seq", "USAGE"),
        },
    )

    failures = validate_neon_schema.validate(conn)

    assert any(
        failure
        == "Runtime role lacks UPDATE on po_history.users. Remediation: "
        "GRANT UPDATE ON TABLE po_history.users TO <runtime_role>;"
        for failure in failures
    )
    assert any(
        "GRANT USAGE ON SEQUENCE po_history.user_access_audit_id_seq"
        in failure
        for failure in failures
    )
    assert not any("DELETE" in failure for failure in failures)


def test_missing_schema_stops_before_object_privilege_checks():
    conn = FakeConnection(schema=False)

    failures = validate_neon_schema.validate(conn)

    assert failures == [
        "Missing schema po_history. Apply neon-schema.sql as the schema owner, "
        "then grant only the runtime privileges listed below."
    ]
    assert len(conn.queries) == 1


def test_validation_reports_missing_column_with_read_only_remediation():
    columns = {
        (table, column): definition
        for table, table_columns in validate_neon_schema.REQUIRED_COLUMNS.items()
        for column, definition in table_columns.items()
    }
    del columns[("users", "email")]

    failures = validate_neon_schema.validate(FakeConnection(columns=columns))

    assert any(
        failure.startswith("Missing column po_history.users.email.")
        and "neon-schema.sql" in failure
        and "made no changes" in failure
        for failure in failures
    )


def test_validation_reports_incompatible_type_and_nullability():
    columns = {
        (table, column): definition
        for table, table_columns in validate_neon_schema.REQUIRED_COLUMNS.items()
        for column, definition in table_columns.items()
    }
    columns[("po_detail", "order_date")] = ("text", False)

    failures = validate_neon_schema.validate(FakeConnection(columns=columns))

    assert any(
        "Incompatible type for po_history.po_detail.order_date: "
        "expected date, found text" in failure
        for failure in failures
    )
    assert any(
        "Incompatible nullability for po_history.po_detail.order_date: "
        "expected nullable, found NOT NULL" in failure
        for failure in failures
    )


def test_validation_reports_incompatible_critical_key():
    keys = {
        (table, key_type): columns
        for table, table_keys in validate_neon_schema.REQUIRED_KEYS.items()
        for key_type, columns in table_keys.items()
    }
    keys[("po_detail", "PRIMARY KEY")] = ("po_num",)

    failures = validate_neon_schema.validate(FakeConnection(keys=keys))

    assert any(
        "Incompatible PRIMARY KEY on po_history.po_detail: "
        "expected (po_num, po_line), found (po_num)" in failure
        and "made no changes" in failure
        for failure in failures
    )


def test_validation_reports_missing_sequence_default_and_ownership():
    defaults = dict(validate_neon_schema.REQUIRED_DEFAULTS)
    del defaults[("users", "id")]
    sequence_owners = dict(validate_neon_schema.REQUIRED_SEQUENCE_OWNERS)
    del sequence_owners["users_id_seq"]

    failures = validate_neon_schema.validate(
        FakeConnection(defaults=defaults, sequence_owners=sequence_owners)
    )

    assert any(
        "Incompatible default for po_history.users.id" in failure
        and "users_id_seq" in failure
        and "found none" in failure
        and "made no changes" in failure
        for failure in failures
    )
    assert any(
        "Incompatible owner for po_history.users_id_seq" in failure
        and "expected po_history.users.id, found none" in failure
        and "SEQUENCE OWNED BY" in failure
        and "made no changes" in failure
        for failure in failures
    )


def test_validation_reports_missing_timestamp_and_status_defaults():
    defaults = dict(validate_neon_schema.REQUIRED_DEFAULTS)
    del defaults[("users", "active")]
    del defaults[("users", "created_at")]
    del defaults[("user_access_audit", "changed_at")]

    failures = validate_neon_schema.validate(FakeConnection(defaults=defaults))

    assert any(
        "Incompatible default for po_history.users.active: expected true, found none"
        in failure
        and "matching DEFAULT from neon-schema.sql" in failure
        for failure in failures
    )
    assert any(
        "Incompatible default for po_history.users.created_at: expected now(), found none"
        in failure
        for failure in failures
    )
    assert any(
        "Incompatible default for po_history.user_access_audit.changed_at: "
        "expected now(), found none" in failure
        for failure in failures
    )


def test_validation_accepts_healthy_sequence_positions():
    conn = FakeConnection(
        sequence_states={
            "users_id_seq": (7, 7, True),
            "user_access_audit_id_seq": (0, 1, False),
        }
    )

    assert validate_neon_schema.validate(conn) == []


def test_validation_accepts_empty_tables_and_never_used_sequences():
    conn = FakeConnection(
        sequence_states={
            "users_id_seq": (None, 1, False),
            "user_access_audit_id_seq": (None, 1, False),
        }
    )

    assert validate_neon_schema.validate(conn) == []


def test_validation_reports_lagging_sequences_with_owner_remediation():
    conn = FakeConnection(
        sequence_states={
            "users_id_seq": (9, 8, True),
            "user_access_audit_id_seq": (20, 20, False),
        }
    )

    failures = validate_neon_schema.validate(conn)

    assert failures == [
        "Sequence po_history.users_id_seq is behind po_history.users.id: "
        "next value is 9, but the maximum stored ID is 9. Remediation: as the "
        "schema owner, run SELECT setval('po_history.users_id_seq', "
        "(SELECT MAX(id) FROM po_history.users), true); this validation made no changes.",
        "Sequence po_history.user_access_audit_id_seq is behind "
        "po_history.user_access_audit.id: next value is 20, but the maximum stored "
        "ID is 20. Remediation: as the schema owner, run SELECT "
        "setval('po_history.user_access_audit_id_seq', "
        "(SELECT MAX(id) FROM po_history.user_access_audit), true); "
        "this validation made no changes.",
    ]