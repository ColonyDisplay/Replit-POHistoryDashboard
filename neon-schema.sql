-- Neon Postgres schema for PO History Detail
-- Translated from the live SQLite DDL in po_detail_report.py and
-- bin_inv_sync.py (snapshot 2026-08-11). If the Python COLUMN_MAPs change,
-- regenerate this file.

-- ── PO history (source: po_detail_report.py) ────────────────────────────────

CREATE TABLE IF NOT EXISTS po_detail (
    po_num        INTEGER,
    po_line       INTEGER,
    order_date    DATE,
    due_date      DATE,
    vendor_id     TEXT,
    vendor_name   TEXT,
    part_num      TEXT,
    description   TEXT,
    class_id      TEXT,
    class_desc    TEXT,
    order_qty     NUMERIC,
    unit_cost     NUMERIC,
    line_total    NUMERIC,
    received_qty  NUMERIC,
    supplier_uom  TEXT,
    inventory_uom TEXT,
    open_order    BOOLEAN,
    entry_person  TEXT,
    terms         TEXT,
    tran_type     TEXT,
    project_id    TEXT,
    buyer_name    TEXT,
    PRIMARY KEY (po_num, po_line)
);

CREATE INDEX IF NOT EXISTS idx_part_num   ON po_detail (part_num);
CREATE INDEX IF NOT EXISTS idx_vendor_id  ON po_detail (vendor_id);
CREATE INDEX IF NOT EXISTS idx_order_date ON po_detail (order_date);

CREATE TABLE IF NOT EXISTS run_log (
    run_timestamp   TIMESTAMPTZ,
    mode            TEXT,
    records_added   INTEGER,
    records_updated INTEGER,
    total_rows      INTEGER,
    max_order_date  DATE
);

-- ── Bin inventory (source: bin_inv_sync.py) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS bin_inventory (
    part_num          TEXT,
    description       TEXT,
    warehouse_code    TEXT,
    warehouse_desc    TEXT,
    bin_num           TEXT,
    on_hand_qty       NUMERIC,
    warehouse_on_hand NUMERIC,
    uom               TEXT,
    class_id          TEXT,
    last_synced       TIMESTAMPTZ,
    PRIMARY KEY (part_num, warehouse_code, bin_num)
);

CREATE INDEX IF NOT EXISTS idx_inv_part ON bin_inventory (part_num);
CREATE INDEX IF NOT EXISTS idx_inv_wh   ON bin_inventory (warehouse_code);

CREATE TABLE IF NOT EXISTS inv_run_log (
    run_timestamp TIMESTAMPTZ,
    mode          TEXT,
    upserted      INTEGER,
    total_rows    INTEGER
);

-- ── Portal users (managed by the app's Users admin page) ────────────────────

CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    email      TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    role       TEXT NOT NULL DEFAULT 'viewer',  -- admin | purchasing | warehouse | viewer
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_access_audit (
    id              BIGSERIAL PRIMARY KEY,
    action          TEXT NOT NULL CHECK (
        action IN ('user_created', 'role_changed', 'activated', 'deactivated', 'access_changed')
    ),
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('admin', 'system')),
    actor_user_id   INTEGER,
    actor_email     TEXT,
    actor_label     TEXT NOT NULL,
    target_user_id  INTEGER NOT NULL,
    target_email    TEXT NOT NULL,
    previous_state  JSONB,
    resulting_state JSONB NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (
            actor_type = 'admin'
            AND actor_user_id IS NOT NULL
            AND actor_email IS NOT NULL
        )
        OR (
            actor_type = 'system'
            AND actor_user_id IS NULL
            AND actor_email IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_user_access_audit_changed_at
    ON user_access_audit (changed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_user_access_audit_target
    ON user_access_audit (target_user_id, changed_at DESC);

-- The app runtime role needs SELECT/INSERT/UPDATE on users, SELECT/INSERT on
-- user_access_audit, and USAGE/SELECT on both SERIAL sequences. Keep
-- UPDATE/DELETE withheld from user_access_audit so recorded access changes
-- remain append-only.
-- Run `python scripts/validate_neon_schema.py` with the runtime role before a
-- release. The check is read-only and reports the exact missing object/grant.

-- Notes for the port (see HANDOFF_POWERBI-VM.md):
-- * SQLite "INSERT OR REPLACE" becomes
--   "INSERT ... ON CONFLICT (<pk>) DO UPDATE SET ...".
-- * SQLite stores dates as TEXT 'YYYY-MM-DD' and booleans as 0/1;
--   the Postgres writer should pass native date/bool values instead of the
--   _row_to_sqlite_tuple() string/int conversions.
-- * A dedicated role with least privilege is recommended:
--   the powerbi-vm writer needs INSERT/UPDATE/DELETE/SELECT;
--   the Replit dashboard role needs SELECT only.
