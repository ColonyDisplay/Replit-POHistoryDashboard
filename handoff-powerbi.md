# Handoff — powerbi-vm: Data Pull + Neon Connection

Audience: the agent (or person) building on **powerbi-vm**, the production
integration machine. Scope: the Epicor → Neon data pipeline only. The
dashboard frontend, auth, and read API are built in Replit from this same
repo (see `handoff-replit.md`) and are **not** part of this work.

```text
powerbi-vm scheduled tasks
  -> po_detail_report.py  (PO history,   weekly incremental)
  -> bin_inv_sync.py      (bin inventory, per current cadence)
  -> Epicor BAQ (epicor.colonydisplay.com)
  -> write to Neon Postgres (sslmode=require)

Replit dashboard (handoff-replit.md)
  -> reads Neon
```

## Files In This Repo You Will Use

| File | Purpose |
|---|---|
| `po_detail_report.py` | PO history sync — Epicor BAQ `PODetailDashboard_CD` → `po_detail` + `run_log` |
| `bin_inv_sync.py` | Bin inventory sync — Epicor BAQ `CD-BinInv-FAST` → `bin_inventory` + `inv_run_log` |
| `Run-PODetail-Report.ps1` | Runner: loads Epicor creds, runs PO sync then inventory sync |
| `Run-BinInv-Sync.ps1` | Runner: inventory sync only |
| `requirements.txt` | Python deps (add `psycopg[binary]` during the port — see below) |
| `neon-schema.sql` | Postgres DDL matching the current SQLite schema exactly |
| `REPLIT_NEON_MIGRATION_PLAN.md` | Overall architecture and phases this handoff implements |

`po_api.py` and `react-ui/` in this repo belong to the Replit track — do not
deploy them on powerbi-vm.

## Current State (What The Scripts Do Today)

Both scripts write to **local SQLite** (`Database/po_history.db`,
`Database/bin_inventory.db`). The work on powerbi-vm is to add a **Postgres
writer targeting Neon** and schedule the runs. Details of the sync logic:

- `po_detail_report.py` modes: `--test` (current year), `--full` (rebuild
  year-by-year from 2010, ~5 min), default = weekly incremental (new POs +
  currently-open + previously-open + trailing 6 months). Checkpoint state is
  derived from the database itself (`MAX(order_date)` + open PO numbers), so
  no checkpoint file needs to move between machines.
- `bin_inv_sync.py`: full-replace upsert of the bin inventory BAQ.
- Both expect `EPICOR_USER` / `EPICOR_PASS` env vars, set by the `.ps1`
  runners from the Credential Helper.

## Machine Prerequisites

1. **Python 3.11+** on PATH, plus `pip install -r requirements.txt`.
2. **Credential Helper** at `C:\VSCode_Projects\Credential Helper\Epicor-Cred.ps1`
   — both runners hardcode this path (dot-source + `Get-EpicorCredential`).
   Keep the same path convention on powerbi-vm, or update the first line of
   both `.ps1` files.
3. **Network access** to `https://epicor.colonydisplay.com` (Epicor BAQ API).
4. **Outbound TLS to Neon** (Postgres over 5432; Neon also offers a
   websocket/443 path if 5432 egress is blocked).
5. Clone of this repo (`ColonyDisplay/Replit-POHistoryDashboard`).

## Build Tasks

### 1. Provision Neon

- Create the Neon project/database (coordinate with the Replit track so
  there is exactly one — this track provisions, the Replit track consumes).
- Run `neon-schema.sql` against it.
- Create two roles: a **writer** (INSERT/UPDATE/DELETE/SELECT) for
  powerbi-vm and a **reader** (SELECT only) for the Replit dashboard.
- Capture the **direct** (non-pooled) connection string for the writer —
  single long-running writer, no need for PgBouncer.
- Hand the **pooled, reader-role** connection string to the Replit track.

### 2. Add the Postgres writer to both sync scripts

- New dependency: `psycopg[binary]` (add to `requirements.txt`).
- Target selected by env var: if `DATABASE_URL` is set, write to Postgres;
  otherwise keep the existing SQLite path (dev fallback and dual-write).
- Port notes:
  - `INSERT OR REPLACE` → `INSERT ... ON CONFLICT (pk) DO UPDATE SET ...`
  - placeholders `?` → `%s`
  - skip `_row_to_sqlite_tuple()` date→string / bool→int coercion for the
    Postgres path; pass native `date` and `bool`
  - `_checkpoint_from_db()` (max order date + open POs) works unchanged
    against Postgres
  - the `PRAGMA`-based `_migrate_db()` is SQLite-only; schema management for
    Neon is `neon-schema.sql`
- Support **dual-write** (SQLite + Neon) during validation — keeps the
  existing internal Docker/WSL dashboard working as a fallback.

### 3. Backfill

Either run `.\Run-PODetail-Report.ps1 --full` against Neon (rebuilds from
2010 straight out of Epicor, ~5 min), or bulk-copy rows from an up-to-date
`po_history.db`. The `--full` rebuild from Epicor is simpler and
authoritative. Then run `.\Run-BinInv-Sync.ps1` once for inventory.

Verify: row counts vs. the SQLite DB, spot-check a handful of part numbers
(last price, order counts), `run_log` has the backfill entry.

### 4. Store the connection string

`DATABASE_URL` must not be committed. Recommended: set it as a machine or
task-level environment variable on powerbi-vm, or extend the Credential
Helper pattern. The `.ps1` runners are the natural place to load it before
invoking Python.

### 5. Schedule

Windows Task Scheduler on powerbi-vm, running as the service account that
owns the Credential Helper secrets:

| Task | Command | Cadence |
|---|---|---|
| PO history + inventory | `powershell -ExecutionPolicy Bypass -File ...\Run-PODetail-Report.ps1` | Weekly (current convention) — consider daily once on Neon |
| Inventory only (optional, fresher) | `powershell -ExecutionPolicy Bypass -File ...\Run-BinInv-Sync.ps1` | Daily or hourly as needed |

### 6. Alerting

The scripts already write `run_log` / `inv_run_log` rows on every run. Add a
freshness check on powerbi-vm (scheduled script or the existing monitoring
pattern): alert if `MAX(run_timestamp)` in Neon is older than the expected
cadence, or if a scheduled task exits non-zero.

## Acceptance Checklist

- [ ] `neon-schema.sql` applied; writer + reader roles exist
- [ ] Incremental run from powerbi-vm completes and upserts into Neon
- [ ] `run_log` row written for that run; row counts match expectations
- [ ] Backfill verified against SQLite (counts + spot checks)
- [ ] Scheduled tasks created and run under the service account
- [ ] `DATABASE_URL` stored outside Git; nothing secret committed
- [ ] Freshness alert in place
- [ ] Reader (SELECT-only) pooled connection string handed to the Replit track

## Reference Documents (this repo)

- `REPLIT_NEON_MIGRATION_PLAN.md` — overall architecture and phases
- `CLERK_M365_AUTH_PLAN.md` — auth design (Replit side; no impact here)
- `PO_Detail_Architecture_Plan.md` — original design history
- `VERCEL_MIGRATION_PLAN.md` — the alternative that was not chosen
