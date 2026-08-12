# Colony PO History Dashboard

FastAPI backend + Vite/React SPA for browsing PO history and bin inventory,
served from Replit and backed by Neon Postgres.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, psycopg (psycopg3), uvicorn |
| Frontend | React 19, Vite 8, AG Grid |
| Database | Neon Postgres (read-only role from powerbi-vm) |
| Auth | Clerk + Microsoft 365 EASIE (to be wired — see `CLERK_M365_AUTH_PLAN.md`) |

## How to run

### Development (no UI build needed)
The workflow **"Colony API"** runs:
```
uvicorn po_api:app --host 0.0.0.0 --port 5000 --reload
```
The React dev server runs separately:
```
cd react-ui && npm run dev
```

### Production-style (API serves built UI)
```
npm ci --prefix react-ui && npm run build --prefix react-ui
uvicorn po_api:app --host 0.0.0.0 --port 5000
```

## Required secrets (Replit Secrets pane)

| Secret | Description |
|---|---|
| `DATABASE_URL` | Neon **pooled** connection string, SELECT-only role, `sslmode=require` |
| `CLERK_SECRET_KEY` | Clerk production secret key |
| `CLERK_JWT_KEY` | PEM public key from Clerk dashboard → API keys |
| `APP_ORIGIN` | Deployment URL (for `authorized_parties`) |
| `ENABLE_SCRIPT_RUNNER` | Set to `0` — script runner is disabled on Replit |
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk publishable key (needed at `npm run build` time) |

`DATABASE_URL` must be set before the API will serve data. The app starts
without it but returns 503 on every data endpoint.

## Project layout

```
po_api.py          FastAPI app (Postgres-backed)
react-ui/          Vite + React SPA
  src/api.js       Fetch helpers (all relative URLs, no hardcoded host)
neon-schema.sql    Postgres DDL — provisioned by powerbi-vm
requirements.txt   Python dependencies
handoff-replit.md  Full build checklist for this Replit track
CLERK_M365_AUTH_PLAN.md  Auth design doc
```

## What's done / what's next

- [x] API ported from SQLite → psycopg / Neon Postgres
- [x] Script runner gated behind `ENABLE_SCRIPT_RUNNER=0`
- [x] `/health` reports `max_order_date` and `data_age_days`
- [ ] Clerk + Microsoft 365 auth (see `CLERK_M365_AUTH_PLAN.md`)
- [ ] `DATABASE_URL` secret — provided by powerbi-vm track after Neon provisioning
- [ ] Remaining secrets set in Replit Secrets pane

## User preferences
