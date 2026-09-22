# Replit Handoff — Add Operations KPI to the Existing PO History App

## Objective

Implement Phases 4 and 5 of the Colony Ops KPI migration **inside the existing
Replit PO History application**:

1. Add a read-only FastAPI API for the published KPI data already in Neon.
2. Add an **Operations KPI** section and pages to the existing React UI.
3. Reuse the app's existing Clerk + Microsoft 365 authentication and Neon
   `replit_reader` connection.

Do not create a second Replit app. Do not add Epicor access to Replit. Do not
change the Windows collector, Neon schema, roles, or existing production data.

## Current production state

- Neon project: `Colony-estimates` (`still-violet-39388347`, Postgres 17,
  `aws-us-east-1`).
- PO History data remains in schema `po_history`.
- Operations KPI read model is already deployed in schema `kpi`.
- `replit_reader` already has additive `USAGE`/`SELECT` access to `kpi`.
- The first successful collector publish is:
  - business date: `2026-08-19` (US Central)
  - run ID: `2`
  - summary metrics: `43`
  - trend metrics: `43`
  - detail payloads: `86` (date + month for every metric)
  - daily values: `43`
- Failed run `1` is not visible through the read views.
- Legacy `public.kpi_daily_value` is unchanged and remains owned by the live
  local dashboard.

## Source repositories

Existing Replit app:

- GitHub: `ColonyDisplay/Replit-POHistoryDashboard`
- Local reference package: `C:\Users\reportpbi-t2\Projects\Replit-POHistoryDashboard`
- Backend entry point: `po_api.py`
- React app: `react-ui/`
- Existing auth design: `CLERK_M365_AUTH_PLAN.md`

KPI contract and reference UI:

- GitHub monorepo: `ColonyDisplay/Colony-Projects`
- Branch: `feature/labor-kpi`
- Project folder: `Colony-Ops-KPI-Dash`
- Frozen contract: `Colony-Ops-KPI-Dash/docs/API-CONTRACT.md`
- API types: `Colony-Ops-KPI-Dash/client/src/types.ts`
- API client: `Colony-Ops-KPI-Dash/client/src/api.ts`
- Reference UI: `Colony-Ops-KPI-Dash/client/src/components/`
- Reference styling/helpers: `Colony-Ops-KPI-Dash/client/src/lib/`
- Neon DDL reference:
  `Colony-Ops-KPI-Dash/db/migrations-cloud/001_kpi_read_model.sql`

Treat the app currently open in Replit as authoritative. The local PO History
package may lag behind Replit; inspect the live Replit workspace before editing.

## Hard boundaries

The Replit implementation must:

- use only the existing server-side `DATABASE_URL` for `replit_reader`;
- query only approved `kpi` views;
- use parameterized SQL;
- preserve the response shapes below;
- keep database credentials out of browser JavaScript;
- use relative `/api/*` URLs;
- apply the same Clerk/M365 protection as the PO History pages and APIs;
- preserve all existing PO History behavior;
- show data freshness and stale/error states.

The Replit implementation must not:

- connect to Epicor SQL or the Epicor API;
- contain Colony Windows/DPAPI credentials;
- use `cloud_admin`, `neondb_owner`, or `kpi_writer`;
- write to Neon;
- query `public.kpi_daily_value` directly;
- expose `DATABASE_URL` to the browser;
- create or migrate database objects;
- deploy as a separate Replit application;
- fall back to live Epicor queries.

## Neon read contract

All reads use views that expose only successful publish runs.

### Summary and trends

View: `kpi.v_api_payload`

Columns:

- `as_of_date`
- `kind` (`kpis` or `trends`)
- `payload` (JSONB)
- `finished_at`
- `run_id`

Parameterized query:

```sql
SELECT payload
FROM kpi.v_api_payload
WHERE kind = %s
  AND as_of_date = %s
ORDER BY run_id DESC
LIMIT 1;
```

If the request omits `asOf`, return the newest successful payload:

```sql
SELECT payload
FROM kpi.v_api_payload
WHERE kind = %s
ORDER BY as_of_date DESC, run_id DESC
LIMIT 1;
```

### Detail

View: `kpi.v_detail_payload`

Columns:

- `metric_id`
- `period_type` (`date` or `month`)
- `period` (`YYYY-MM-DD` or `YYYY-MM`)
- `row_count`
- `payload` (JSONB)
- `finished_at`
- `run_id`

Parameterized query:

```sql
SELECT payload
FROM kpi.v_detail_payload
WHERE metric_id = %s
  AND period_type = %s
  AND period = %s
ORDER BY run_id DESC
LIMIT 1;
```

### Health and freshness

View: `kpi.v_publish_status`

```sql
SELECT latest_as_of, last_success_at, failures_7d
FROM kpi.v_publish_status;
```

Freshness uses `America/Chicago`. The expected date is the prior weekday
(Mon–Fri). Report `stale` when `latest_as_of` is older than that date.

## Required FastAPI routes

### `GET /api/kpis?asOf=YYYY-MM-DD`

Return the stored `OpsKpiResponse` JSON payload unchanged:

```json
{
  "asOf": "2026-08-19",
  "historyEnabled": true,
  "sections": [
    {
      "id": "shipping-receiving",
      "title": "Shipping / Receiving",
      "metrics": [
        {
          "id": "SH-01",
          "label": "Units shipped",
          "unit": "EA",
          "daily": 0,
          "mtd": 0,
          "avg7": 0,
          "status": "ok",
          "note": "optional",
          "subsection": "optional"
        }
      ]
    }
  ]
}
```

### `GET /api/kpis/trends?asOf=YYYY-MM-DD`

Return the stored `KpiTrendsResponse` unchanged:

```json
{
  "asOf": "2026-08-19",
  "historyEnabled": true,
  "metrics": {
    "SH-01": {
      "id": "SH-01",
      "label": "Units shipped",
      "unit": "EA",
      "sectionId": "shipping-receiving",
      "grain": "daily_activity",
      "fromHistory": false,
      "dailyLast30": [{"date": "2026-08-19", "value": 0}],
      "monthlyTrailing12": [
        {"year": 2026, "month": 8, "label": "Aug 26", "value": 0}
      ]
    }
  }
}
```

### `GET /api/kpis/{metricId}/detail?date=YYYY-MM-DD`

### `GET /api/kpis/{metricId}/detail?month=YYYY-MM`

Exactly one of `date` or `month` is required. Return the stored
`KpiDetailResponse` unchanged:

```json
{
  "metricId": "SH-01",
  "label": "Units shipped",
  "unit": "EA",
  "period": "2026-08-19",
  "rangeStart": "2026-08-19",
  "rangeEnd": "2026-08-19",
  "rowCount": 0,
  "totals": {"qty": 0, "dollars": null},
  "rows": []
}
```

### Health

Keep the existing PO History `/health` response unchanged. Add a separate
`/api/health` endpoint for KPI freshness and compatibility with the KPI UI.
An aggregate health response can be considered later, but is not required for
this migration.

Minimum KPI health fields:

```json
{
  "status": "ok",
  "state": "ok",
  "database": "neon",
  "databaseStatus": "connected",
  "appVersion": "deployment identifier",
  "latestSuccessfulPublish": "2026-08-19",
  "lastSuccessAt": "timestamp",
  "expectedBusinessDate": "2026-08-19",
  "failures7d": 1
}
```

States are `ok`, `stale`, or `error`. Do not include hosts, usernames,
connection strings, SQL, or raw database errors.

## Validation and error responses

- `asOf` and `date`: strict `YYYY-MM-DD` and real calendar dates.
- `month`: strict `YYYY-MM`.
- `metricId`: allow only known IDs or a strict `^[A-Z0-9-]{2,32}$` pattern,
  then return 404 if no payload exists.
- `date` and `month` together: HTTP 400.
- neither `date` nor `month`: HTTP 400.
- no successful publish for date/period: HTTP 404.
- Neon unavailable: HTTP 503 with sanitized text.

Keep the frozen error shape because the reference UI reads `details` then
`error`:

```json
{"error": "Invalid asOf date", "details": "Use ?asOf=YYYY-MM-DD"}
```

## Backend implementation guidance

1. Reuse the Replit app's current Postgres connection helper/pool.
2. Ensure the connection uses the server-side `DATABASE_URL` containing the
   `replit_reader` role.
3. Enforce read-only access in a pooling-safe way: use `BEGIN READ ONLY` per
   transaction or the connection startup `options` parameter. Do not rely on a
   session-level `SET` with Neon's transaction-pooled endpoint.
4. Put KPI queries in a small repository module and routes in a dedicated
   FastAPI router.
5. Include the KPI router before the static SPA mount.
6. Do not run schema migrations on app startup.
7. Apply the existing Clerk auth dependency to the three KPI data routes.
8. Confirm the existing PO History data routes are protected too. Do not leave
   PO data or `/run-script` unauthenticated while protecting only KPI routes.
9. Disable `/scripts` and `/run-script` in Replit with
   `ENABLE_SCRIPT_RUNNER=0`; they are Windows-only and should return 404/403.
10. Keep health public and sanitized for uptime monitoring.
11. Keep response JSON exactly as stored; do not recalculate KPIs in Replit.
12. Set reasonable connection/query timeouts and response limits.
13. Keep KPI dependencies isolated from PO History startup. If a guarded router
    import is used, log a sanitized warning and make `/api/health` report the
    error; a missing KPI dependency must not take existing PO pages offline.

The Replit environment can use normal `psycopg` access to Neon's pooled
endpoint. The Windows production machine's port-5432 firewall restriction does
not apply inside Replit.

## React integration

Add **Operations KPI** to the existing application navigation. It is a section
of the PO History app, not a separate SPA or deployment.

Port/adapt the reference components from
`Colony-Ops-KPI-Dash/client/src/components/`:

- `OpsKpiDashboard.tsx`
- `KpiMetricCard.tsx`
- `SectionTabs.tsx`
- `DetailPanel.tsx`
- `PanelErrorBoundary.tsx`

Also adapt:

- `client/src/types.ts`
- `client/src/lib/dates.ts`
- `client/src/lib/format.ts`
- `client/src/lib/theme.ts`

The target PO History UI currently uses JSX, so either:

- convert the KPI TypeScript components to JSX; or
- enable TypeScript in the existing Vite app without rewriting existing JSX.

Verify both `recharts` and `@clerk/react` are declared in
`react-ui/package.json` and `package-lock.json`; having a package only in
`node_modules` is not sufficient because Replit deploys with `npm ci`. Reuse
the existing app's Clerk provider/session handling rather than creating a
second provider.

For local Vite development, add an `/api` proxy to the FastAPI port alongside
the existing PO route proxies:

```js
server: {
  proxy: {
    '/api': 'http://localhost:8000',
  },
}
```

Scope existing global `table`, `th`, `td`, and hover CSS rules to the PO
History table wrappers so they do not override the KPI detail drawer. Wrap the
KPI page in the ported `PanelErrorBoundary` so a KPI render failure cannot
blank the PO History application.

Preserve the curated `SUMMARY_BLOCKS` behavior from the reference
`OpsKpiDashboard.tsx`, including its derived Average $ / unit metric. Do not
replace Daily Summary with an arbitrary `section.metrics.slice(0, 4)`.

### Required UI behavior

- Existing PO History pages continue to work unchanged.
- New top-level navigation item: **Operations KPI**.
- Relative API calls:
  - `/api/kpis?asOf=...`
  - `/api/kpis/trends?asOf=...`
  - `/api/kpis/{metricId}/detail?...`
  - `/api/health`
- Every protected API call carries the existing Clerk Bearer token.
- Date picker defaults to the prior business day in US Central.
- Visible **Data as of** date.
- Visible stale banner when health state is `stale`.
- Visible error state with retry.
- Section tabs and metric cards.
- 30-day and monthly trends.
- Metric detail panel/drawer using the published detail route.
- Desktop display remains the primary layout; do not break responsive use.
- Browser code contains no Neon connection details.
- `npm ci --prefix react-ui` and the production Vite build both succeed from a
  clean dependency install.

The published response contains 43 metrics across:

- Shipping / Receiving
- Shipping Redux
- Inventory
- Fabrication
- Assembly

Use the `sections` array from the payload rather than hard-coding section
membership.

Detail payloads exist only for dates/months that the collector has published.
With the current data, `date=2026-08-19` and `month=2026-08` are valid. Treat
404 for another date/month as "not published yet," not as a live-Epicor
fallback condition.

## Authentication

Reuse the existing app's Clerk + Microsoft 365 implementation:

- Microsoft EASIE connection for `colonydisplay.com`;
- `ClerkProvider` in the React entry point;
- signed-out users redirected to Clerk sign-in;
- `UserButton` in the shared app header;
- `getToken()` Bearer token on API requests;
- networkless RS256 verification using Clerk's official
  `clerk-backend-api` package with `CLERK_JWT_KEY`;
- validate `azp` against `APP_ORIGIN`;
- all PO History and KPI data routes return 401 without a valid session;
- `/scripts` and `/run-script` are disabled in the Replit environment;
- health and static SPA assets remain public.

Do not create a second Clerk application.
Do not implement ad-hoc JWT decoding with signature/audience checks disabled;
use Clerk's `authenticate_request()` and `AuthenticateRequestOptions`.

## Replit secrets

Use the secrets already assigned to the PO History app:

| Secret | Required use |
|---|---|
| `DATABASE_URL` | Existing pooled Neon `replit_reader` URL |
| `CLERK_SECRET_KEY` | Existing Clerk production secret |
| `CLERK_JWT_KEY` | Existing PEM key for networkless verification |
| `APP_ORIGIN` | Exact Replit deployment origin |
| `VITE_CLERK_PUBLISHABLE_KEY` | Existing build-time Clerk key |
| `ENABLE_SCRIPT_RUNNER` | `0` in Replit |
| `AUTH_REQUIRED` | `1` in Replit (`0` is allowed only for explicit local development) |
| `TZ` | `America/Chicago` |

Never paste any secret into source, logs, chat output, or browser environment
except the Clerk publishable key designed for frontend use.

Also update `.env.example` with placeholders for
`VITE_CLERK_PUBLISHABLE_KEY`, `CLERK_JWT_KEY`, `APP_ORIGIN`,
`AUTH_REQUIRED`, `ENABLE_SCRIPT_RUNNER`, and `TZ`. Never put real values in
that file.

## Tests required before deployment

Backend tests:

- authenticated `GET /api/kpis?asOf=2026-08-19` returns 43 metrics;
- authenticated trends route returns 43 metric series;
- authenticated date detail returns the stored payload;
- authenticated month detail returns the stored payload;
- invalid dates/months return 400;
- unknown date/metric/period returns 404;
- data routes without a session return 401;
- health is public and reports latest date/state;
- database errors return sanitized 503 responses;
- tests assert no write SQL is used.

Frontend checks:

- existing PO search, summary, BOM lookup, and inventory still render;
- Operations KPI navigation opens the new section;
- loading, empty, stale, and error states render;
- date change reloads summary and trends;
- section tabs work;
- metric click opens detail;
- Clerk token is sent on data calls;
- production Vite build succeeds.

Live staging smoke test:

1. Sign in with an approved `colonydisplay.com` Microsoft account.
2. Open Operations KPI.
3. Verify Data as of `2026-08-19` is available.
4. Compare several metrics with the current local dashboard for that date.
5. Open daily and monthly details.
6. Confirm `/api/health` is non-stale.
7. Confirm an unauthenticated API request returns 401.
8. Confirm the browser has no Neon/Epicor secret.
9. Confirm existing PO History pages still work.

## Build and deployment

Use the existing app's deployment, URL, build command, and run command. Do not
create another deployment.

Typical commands (adjust only if the actual Replit app already differs):

```bash
npm ci --prefix react-ui
npm run build --prefix react-ui
uvicorn po_api:app --host 0.0.0.0 --port "$PORT"
```

Deploy to the existing app's staging/development deployment first. Do not
replace the current local Ops Dashboard or direct users to the Replit KPI pages
until contract tests, reconciliation, Clerk sign-in, and user acceptance pass.

## Definition of done for Replit Phases 4–5

- [ ] KPI backend reads Neon only through `replit_reader`.
- [ ] Frozen summary, trends, detail, and health routes pass tests.
- [ ] Replit has no Epicor dependency or write credential.
- [ ] Clerk/M365 protects KPI data routes and pages.
- [ ] Operations KPI appears inside the existing PO History app.
- [ ] Date selection, sections, trends, and details work.
- [ ] Data timestamp, stale state, and error state are visible.
- [ ] Existing PO History behavior remains intact.
- [ ] Production frontend build succeeds.
- [ ] Replit staging smoke test passes.
- [ ] No secrets are committed or exposed to the browser.
