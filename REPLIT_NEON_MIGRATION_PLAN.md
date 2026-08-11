# Replit + Neon Migration Plan — PO History Detail

Alternative to `VERCEL_MIGRATION_PLAN.md`: host the dashboard (FastAPI + React)
on Replit and move the data from local SQLite to Neon Postgres.

## Why Replit Instead Of Vercel

The Vercel plan's biggest friction was that Vercel cannot run Uvicorn as a
permanent web server, forcing an API rewrite into serverless functions.

Replit removes that constraint:

- Replit Deployments (Reserved VM or Autoscale) run a long-lived process —
  `uvicorn po_api:app` works as-is.
- The FastAPI app can keep serving the built React UI from `react-ui/dist`,
  exactly like the current local/Docker runtime.
- No route-by-route rewrite. The only mandatory code change is the database
  layer (SQLite → Postgres).

Replit's own built-in SQL database is Neon-backed Postgres, so the pairing is
native to the platform either way.

## Current Architecture (What Has To Move)

| Component | Today | Replit/Neon Target |
|---|---|---|
| API | FastAPI (`po_api.py`), Uvicorn :8000, Docker in WSL | Same FastAPI app, deployed on Replit |
| Frontend | React + Vite, built to `react-ui/dist`, served by FastAPI | Same, built during Replit deploy |
| PO data | SQLite `Database/po_history.db` (`po_detail`, `run_log`) | Neon Postgres |
| Inventory data | SQLite `Database/bin_inventory.db` (`bin_inventory`) | Neon Postgres (same database, second table) |
| Refresh | `Run-PODetail-Report.ps1` / `Run-BinInv-Sync.ps1` on Windows, pulls Epicor BAQ | Scheduled on **powerbi-vm** (production integration machine); writes to Neon over TLS |
| Script runner | `/scripts` + `/run-script` execute local PowerShell | **Cannot move** — see below |

## Hard Constraints

### 1. Epicor access stays internal

The refresh scripts hit `epicor.colonydisplay.com` with credentials from the
Credential Helper. Do not move the sync jobs to Replit. They run as scheduled
tasks on **powerbi-vm**, the production integration machine — not on the dev
machine where this project is edited. The only code change is the write
target (Neon instead of local SQLite).

powerbi-vm needs: the deployed project code, a Python environment with
`psycopg`, the Epicor credential files (`Epicor-Cred.ps1` pattern), the Neon
direct connection string as a secret, and outbound HTTPS/TLS (port 5432 or
Neon's pooled 443 proxy) to Neon.

```text
powerbi-vm scheduled task
  -> po_detail_report.py / bin_inv_sync.py
  -> Epicor BAQ
  -> write to Neon Postgres (sslmode=require)

Replit deployment
  -> FastAPI reads Neon
  -> serves React dashboard
```

### 2. `/run-script` cannot run on Replit

`POST /run-script` launches `powershell.exe` against whitelisted local
scripts. A Replit container has no access to any Windows machine. In
production those scripts live on powerbi-vm, so the whitelist paths in
`po_api.py` must match powerbi-vm's deployment layout, not the dev machine's
`C:\VSCode_Projects\...` paths. Options, in order of preference:

1. **Drop it from the Replit deployment** — gate the script-runner routes
   behind an env flag (`ENABLE_SCRIPT_RUNNER=0` on Replit). Script execution
   stays on an internal instance running on powerbi-vm.
2. **Job-queue pattern** — Replit writes a "run requested" row to a Neon
   `job_queue` table; a poller on powerbi-vm picks it up, runs the script,
   and writes results back. Only build this if remote triggering is genuinely
   needed from outside the LAN.

### 3. The public URL needs authentication

Today the dashboard is LAN-only. A Replit deployment is on the public
internet. PO pricing history is sensitive vendor data — do not ship without
authentication. This is a go/no-go gate, not a nice-to-have.

**Decision: Clerk with Microsoft 365 (Entra ID) sign-in.** Estimators sign in
with their existing M365 work accounts; Clerk provides the sign-in UI, session
management, and user administration. Full design, code changes, and rollout
phases are in `CLERK_M365_AUTH_PLAN.md` — the auth layer is shared with the
Vercel plan and is hosting-agnostic.

## Database Migration: SQLite → Neon

### Schema

Same shape as SQLite with Postgres types. One Neon project, one database, all
tables together:

```sql
CREATE TABLE po_detail (
    po_num       INTEGER,
    po_line      INTEGER,
    order_date   DATE,
    due_date     DATE,
    vendor_id    TEXT,
    vendor_name  TEXT,
    part_num     TEXT,
    description  TEXT,
    class_id     TEXT,
    class_desc   TEXT,
    order_qty    NUMERIC,
    unit_cost    NUMERIC,
    line_total   NUMERIC,
    received_qty NUMERIC,
    pum          TEXT,
    open_order   BOOLEAN,
    entry_person TEXT,
    terms        TEXT,
    tran_type    TEXT,
    project_id   TEXT,
    buyer_name   TEXT,
    PRIMARY KEY (po_num, po_line)
);
CREATE INDEX idx_part_num   ON po_detail (part_num);
CREATE INDEX idx_vendor_id  ON po_detail (vendor_id);
CREATE INDEX idx_order_date ON po_detail (order_date);

-- run_log and bin_inventory ported the same way
```

Match the real SQLite DDL in `po_detail_report.py` / `bin_inv_sync.py` at
migration time (columns have drifted since the original plan; e.g.
`buyer_name` was added later).

### Code changes

- `po_api.py`: replace `sqlite3.connect` with a Postgres driver
  (`psycopg[binary]` + a small connection pool). Placeholders change from `?`
  to `%s`; `sqlite3.Row` → `dict_row` row factory. Query logic is otherwise
  portable — no SQLite-specific SQL is in use.
- `po_detail_report.py` / `bin_inv_sync.py`: swap the SQLite upsert
  (`INSERT ... ON CONFLICT` works in both engines) to write to Neon via
  `DATABASE_URL`. Keep an optional `--sqlite` flag or env switch so the local
  stack still works as a fallback during cutover.
- Checkpoint logic (`_checkpoint_from_db`) reads max order date and open POs
  from the DB — works unchanged against Postgres.

### Data seed

One-time backfill: read every row out of the local SQLite files and bulk-insert
into Neon (`COPY` or batched executemany). Verify row counts and a few
spot-check parts against `/summary/{part_num}` before cutover.

## Replit Deployment Design

### Deployment type

- **Reserved VM** — always-on, fixed monthly cost, no cold starts. Right
  choice if estimators use this all day.
- **Autoscale** — scales to zero, pay per use, but cold starts add latency to
  the first request. Acceptable for occasional lookups.

Recommendation: start with Autoscale (cheap), move to Reserved VM if cold
starts annoy the estimating team.

### App config on Replit

- Run command: `uvicorn po_api:app --host 0.0.0.0 --port $PORT`
- Build step: `npm ci --prefix react-ui && npm run build --prefix react-ui`
  so `react-ui/dist` exists in the deployment image.
- Secrets (Replit Secrets pane, never committed):
  - `DATABASE_URL` — Neon pooled connection string (`sslmode=require`)
  - `ENABLE_SCRIPT_RUNNER=0`
  - `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, `APP_ORIGIN` — backend auth
    (see `CLERK_M365_AUTH_PLAN.md`)
  - `VITE_CLERK_PUBLISHABLE_KEY` — must be present at build time (Vite
    inlines it into the bundle during `npm run build`)
- CORS: the current `allow_origins` list is localhost-only. Since FastAPI
  serves the UI same-origin on Replit, no new origins are needed — but remove
  the localhost entries in the deployed config.

### Neon connection notes

- Use the **pooled** connection string (PgBouncer) from Replit — Autoscale can
  fan out instances and exhaust direct connections.
- The refresh scripts on powerbi-vm can use the direct (non-pooled)
  connection string since they are a single long-running writer.
- Neon scale-to-zero: first query after idle has a short compute wake-up.
  Fine for this workload; disable scale-to-zero later if it bothers users.

## Migration Phases

### Phase 1 — Provision Neon

Create Neon project, database, schema (tables + indexes above). Capture pooled
and direct connection strings.

### Phase 2 — Point Refresh At Neon

Add Postgres write support to `po_detail_report.py` and `bin_inv_sync.py`.
Develop and test on the dev machine, then deploy to **powerbi-vm**: project
code, Python environment, Epicor credential files, Neon connection string,
and the scheduled tasks (weekly PO detail, plus the bin-inventory cadence).
Run a full backfill into Neon, then run the scheduled incremental from
powerbi-vm and confirm `run_log` entries and checkpoint behaviour match the
SQLite runs. Dual-write (SQLite + Neon) during the validation window.

### Phase 3 — Port The API

Swap the DB layer in `po_api.py` to Postgres behind a `DATABASE_URL` env var.
Gate `/scripts` and `/run-script` behind `ENABLE_SCRIPT_RUNNER`. Test every
endpoint locally against Neon before touching Replit.

### Phase 4 — Add Auth

Implement Clerk + Microsoft 365 sign-in per `CLERK_M365_AUTH_PLAN.md`
(Phases A–B there: Clerk app with the EASIE Microsoft connection, React
provider + token header, FastAPI `require_auth` dependency, production Entra
credentials). Phase gate: do not deploy publicly without it.

### Phase 5 — Deploy To Replit

Create the Repl from the GitHub repo (ColonyDisplay org), configure secrets,
build the React UI, deploy. Smoke-test `/health`, part search, summary,
inventory, bulk lookup from an off-LAN device.

### Phase 6 — Cutover And Fallback

- Point estimators at the Replit URL.
- Keep the internal Docker/WSL stack running for at least one refresh cycle as
  fallback (it still reads local SQLite, which Phase 2 dual-write keeps fresh).
- After a clean week: stop dual-writing SQLite, keep the internal stack only
  for `/run-script`, or decommission it entirely if the job-queue pattern was
  built.

### Phase 7 — Observability

- `/health` extended to report row count **and** max `order_date` age — data
  freshness matters as much as uptime.
- External uptime monitor on the Replit URL.
- Refresh script failure alerting stays on powerbi-vm (the scripts already
  log to `run_log`; alert when the latest run is older than the expected
  cadence).

## Comparison With The Vercel Plan

| | Vercel (full) | Replit + Neon |
|---|---|---|
| API rewrite | Required (serverless functions) | None — Uvicorn runs as-is |
| Data move to cloud | Required (Neon) | Required (Neon) — same work |
| Always-on process | Not supported | Supported (Reserved VM) |
| Script runner | Impossible | Impossible on-platform; env-gated or job queue |
| Auth burden | Same — Clerk + M365 (`CLERK_M365_AUTH_PLAN.md`) | Same — Clerk + M365 (`CLERK_M365_AUTH_PLAN.md`) |
| Ongoing cost | Function invocations | Autoscale usage or flat Reserved VM |

The Neon migration (Phases 1–3) is identical work under both plans. Doing it
first keeps both hosting options open — the hosting choice only affects
Phases 4–6.

## Recommended Path

```text
1. Provision Neon, port refresh scripts, backfill (Phases 1–2)
2. Port po_api.py to Postgres, validate locally (Phase 3)
3. Add auth, deploy to Replit Autoscale (Phases 4–5)
4. Cut over with the internal stack as fallback (Phase 6)
```

Total code churn is small: one DB layer in three Python files, one env-gated
route group, one auth middleware. No frontend changes beyond rebuild.
