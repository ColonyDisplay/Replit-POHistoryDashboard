# Handoff — Replit: Dashboard Frontend, API, Auth, and Neon

Audience: the agent (or person) building the dashboard in Replit. Scope:
the FastAPI read API, the React UI, and Clerk + Microsoft 365
authentication, all reading from Neon Postgres. The Epicor → Neon data
pipeline is **not** part of this work — it runs on powerbi-vm (see
`handoff-powerbi.md`) and this app only reads what it writes.

```text
Browser (estimators, M365 sign-in via Clerk)
  -> Replit deployment
       FastAPI (po_api.py, ported to Postgres)
       serves React UI from react-ui/dist
  -> reads Neon Postgres (SELECT-only role)
```

## Files In This Repo You Will Use

| Path | Purpose |
|---|---|
| `po_api.py` | FastAPI app — all endpoints, currently reads local SQLite |
| `react-ui/` | Vite + React SPA, built to `react-ui/dist`, served by FastAPI |
| `requirements.txt` | Python deps (add `psycopg[binary]` and `clerk-backend-api`) |
| `neon-schema.sql` | The schema this app queries |
| `REPLIT_NEON_MIGRATION_PLAN.md` | Full migration plan this handoff implements |
| `CLERK_M365_AUTH_PLAN.md` | Complete auth design — follow it as written |

`po_detail_report.py`, `bin_inv_sync.py`, and the `.ps1` runners belong to
the powerbi-vm track — they do not run on Replit.

## Build Tasks

### 1. Import this repo into Replit

Import `ColonyDisplay/Replit-POHistoryDashboard` from GitHub. The app root
is the repo root (`po_api.py` at top level, UI in `react-ui/`).

### 2. Port `po_api.py` to Postgres

- Replace `sqlite3.connect(DB_PATH)` / `sqlite3.connect(INV_PATH)` with a
  `psycopg` connection pool using `DATABASE_URL`. Both former databases are
  tables in the same Neon database (`po_detail`, `bin_inventory`, plus logs).
- `?` placeholders → `%s`; `sqlite3.Row` → `psycopg.rows.dict_row`.
- The SQL itself ports cleanly — no SQLite-specific syntax is in use.
- Use the **pooled** (PgBouncer) Neon connection string — Replit Autoscale
  can fan out instances — with the **SELECT-only** role provided by the
  powerbi-vm track.

### 3. Gate the script runner

`/scripts` and `/run-script` execute PowerShell on a Windows machine and
must not be reachable from Replit. Wrap them behind an env flag and set
`ENABLE_SCRIPT_RUNNER=0` in the deployment. (Script execution stays
internal; see the job-queue option in the migration plan if remote
triggering is ever required.)

### 4. Implement Clerk + Microsoft 365 auth

Follow `CLERK_M365_AUTH_PLAN.md` in full. Condensed:

- Clerk app with an **EASIE Microsoft** enterprise connection on the
  `colonydisplay.com` domain; all other sign-in strategies disabled.
- React: `@clerk/react`, `ClerkProvider` + `SignedIn`/`SignedOut` redirect
  in `main.tsx`/`main.jsx`, Bearer token from `getToken()` on every API
  call (the fetch helper is in `react-ui/src/api.js`), `<UserButton />` in
  the header.
- FastAPI: `clerk-backend-api` package, app-wide `require_auth` dependency,
  networkless verification via `CLERK_JWT_KEY`, `authorized_parties` pinned
  to the deployment URL. `/health` and the static mount stay public.

### 5. Deployment configuration

- Build: `npm ci --prefix react-ui && npm run build --prefix react-ui`
  (`VITE_CLERK_PUBLISHABLE_KEY` must be present **at build time** — Vite
  inlines it).
- Run: `uvicorn po_api:app --host 0.0.0.0 --port $PORT`
- Deployment type: start with Autoscale; move to Reserved VM if cold starts
  bother users.
- Secrets (Replit Secrets pane):

| Secret | Value |
|---|---|
| `DATABASE_URL` | Neon **pooled** connection string, SELECT-only role, `sslmode=require` |
| `CLERK_SECRET_KEY` | Clerk production secret key |
| `CLERK_JWT_KEY` | PEM public key (Clerk dashboard → API keys) |
| `APP_ORIGIN` | The deployment URL (for `authorized_parties`) |
| `ENABLE_SCRIPT_RUNNER` | `0` |
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk publishable key (build-time) |

- CORS: FastAPI serves the UI same-origin, so drop the localhost
  `allow_origins` entries in the deployed configuration.

### 6. Health / freshness

Extend `/health` to also report `MAX(order_date)` age so the uptime monitor
catches a stalled powerbi-vm pipeline, not just a down web app.

## Acceptance Checklist

- [ ] All endpoints return correct data from Neon (search, part history,
      summary, bulk-lookup, inventory routes)
- [ ] Unauthenticated API requests return 401; static UI + `/health` load
      without a session
- [ ] Sign-in round-trips through Microsoft; a `colonydisplay.com` account
      gets in, an external account is rejected
- [ ] `/scripts` and `/run-script` return 404/403 on the deployment
- [ ] Off-LAN smoke test passes (search a part, view summary, inventory)
- [ ] No secrets in the repo; all six secrets set in Replit

## Coordination With powerbi-vm

- One Neon database, two roles. The powerbi-vm track provisions Neon and
  hands this track the pooled reader connection string.
- Do not point this app at Neon until the backfill in `handoff-powerbi.md`
  is verified, or every search will come back empty.
