# Vercel Migration Plan — PO History Detail

## Current Architecture

- Backend: Python + FastAPI in `po_api.py`
- HTTP server: Uvicorn on port 8000
- Frontend: React + Vite in `react-ui/`
- Production-style local runtime: FastAPI serves the built React UI from `react-ui/dist`
- Data: local SQLite database at `Database/po_history.db`
- Data refresh: local scripts such as `Run-PODetail-Report.ps1`

This project is a traditional always-on Python web app. Vercel can host static frontend output and serverless functions, but it is not designed to run Uvicorn as a permanent web server.

## Target Architecture Options

### Option A — Keep FastAPI/Uvicorn Off Vercel

Use Vercel for the React frontend only and keep the FastAPI API internal.

```text
Browser
  -> Vercel static React app
  -> internal FastAPI API
  -> SQLite/internal data
```

This is the least code churn, but it requires network access from users/browser to the internal API and careful CORS/security handling. See the Authentication section below — the API must require Clerk session tokens before it is exposed beyond the LAN.

### Option B — Migrate API To Vercel Functions

Move API endpoints from FastAPI route handlers into Vercel functions.

```text
Browser
  -> Vercel static React app
  -> Vercel API functions
  -> cloud database/storage
```

This is more Vercel-native, but it requires replacing the local SQLite dependency with a cloud-accessible store such as Neon Postgres.

### Option C — Move To A Vercel-Native Node/Next App

Rewrite the API layer to Node/Next route handlers and keep the React UI in the same app.

This is the most work and should only be chosen if the project is being productized long-term on Vercel.

## Uptime Strategy On Vercel

Do not migrate the local watchdog directly. Vercel does not keep a single Uvicorn process running.

Use:

- Vercel platform lifecycle for serverless functions
- `/health` or `/api/health` endpoint for dependency checks
- external uptime monitoring for alerting
- Vercel deployment rollback for bad releases
- Cron jobs only for cloud-safe scheduled work

If the API remains internal, keep the local watchdog for the internal FastAPI service and monitor both:

- Vercel frontend availability
- internal API health

## Authentication — Clerk + Microsoft 365

Any Vercel deployment puts the dashboard on the public internet, and PO
pricing history is sensitive vendor data. Authentication is a go/no-go gate
before either Option A or Option B ships.

**Decision: Clerk with Microsoft 365 (Entra ID) sign-in**, detailed in
`CLERK_M365_AUTH_PLAN.md` (shared with the Replit plan — the auth layer is
hosting-agnostic). Summary:

- Clerk EASIE Microsoft enterprise connection, enrolled on the
  `colonydisplay.com` email domain. Estimators sign in with existing M365
  accounts; users are provisioned on first sign-in and deprovisioned when
  removed in Entra.
- React SPA wraps in `ClerkProvider` (`@clerk/react`), redirects signed-out
  users to Microsoft sign-in, and attaches the Clerk session token as a
  Bearer header on every API call. `VITE_CLERK_PUBLISHABLE_KEY` must be set
  in the Vercel build environment.
- Backend verification depends on the option chosen:
  - **Option A (FastAPI stays internal):** `clerk-backend-api` Python package
    with a `require_auth` dependency, networkless JWT verification via
    `CLERK_JWT_KEY`. CORS must allow the Vercel origin and the
    `Authorization` header.
  - **Option B (Vercel functions):** `@clerk/backend`'s
    `authenticateRequest()` in each function (or the same Python package if
    the functions stay Python), same networkless `jwtKey` approach.
- User management (access review, bans, removals) happens in the Clerk
  dashboard; identity stays in Entra.

## Key Migration Constraint: SQLite

SQLite is the biggest blocker for a full Vercel migration.

Local SQLite works well for the current internal app, but Vercel functions have ephemeral runtime filesystems. A Vercel function should not depend on writing to `Database/po_history.db`.

For full Vercel hosting, move data to:

- Neon Postgres, preferred for relational reporting data
- another managed Postgres provider
- object storage only if the app is changed to read static snapshots

Recommended data flow:

```text
Refresh script (scheduled on powerbi-vm, the production integration machine)
  -> Epicor/report source
  -> write PO history data to Neon

Vercel app
  -> read Neon
```

## Migration Phases

### Phase 1 — Inventory Routes And Data Dependencies

List all FastAPI endpoints in `po_api.py` and document:

- input parameters
- database tables/queries used
- whether the endpoint reads only or writes data
- whether it depends on local files

### Phase 2 — Decide Hosting Boundary

Choose one:

1. Frontend on Vercel, FastAPI remains internal.
2. Full migration to Vercel functions with cloud database.
3. Keep project off Vercel and instead run FastAPI headless as a Windows service or scheduled startup app.

For a documentation/reporting tool, option 1 may be enough. For external access and Vercel-native uptime, option 2 is cleaner.

### Phase 3 — Move Data Off Local SQLite If Needed

If choosing full Vercel migration:

- create cloud schema equivalent to `Database/po_history.db`
- migrate existing data
- update refresh scripts to write to cloud DB
- update API queries to use the cloud DB

Keep SQLite only as local/dev fallback if useful.

### Phase 4 — API Migration

If staying Python:

- evaluate whether Vercel Python functions are sufficient for the route set
- avoid long-running background loops inside functions
- avoid filesystem writes

If moving to Node/Next:

- port route logic endpoint-by-endpoint
- reuse SQL/query semantics but rewrite database access
- keep frontend API calls relative

### Phase 5 — Frontend Build

Keep Vite for development and build only.

Production flow:

```text
npm run build --prefix react-ui
react-ui/dist -> Vercel static output
```

No Vite dev server runs in production.

### Phase 6 — Scheduled Refresh

Current refresh scripts remain internal and run as scheduled tasks on
**powerbi-vm**, the production integration machine — not the dev machine.
powerbi-vm needs the deployed project code, a Python environment, the Epicor
credential files, and the cloud DB connection string.

Preferred:

```text
powerbi-vm scheduled task
  -> refresh PO history
  -> write cloud DB
  -> Vercel app reads cloud DB
```

Only move refresh to Vercel Cron if it can run without local files, local network dependencies, or Windows-only assumptions.

### Phase 7 — Observability

Add:

- health endpoint
- structured request logs
- refresh job success/failure logs
- alerting when data age exceeds expected threshold

For this app, data freshness is as important as web uptime.

## Recommended Path

For minimum risk:

```text
Phase 1: keep FastAPI/Uvicorn internal
Phase 2: add Clerk + M365 auth (CLERK_M365_AUTH_PLAN.md) before any public exposure
Phase 3: deploy React frontend to Vercel only if browser access to API is solved
Phase 4: move SQLite data to Neon if full Vercel hosting is required
Phase 5: migrate API endpoints after data is cloud-ready
```

Do not choose Vercel as the full target until the SQLite/data-refresh story is resolved. The web framework choice is secondary to the data hosting decision.
