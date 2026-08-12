# Colony PO History Dashboard

FastAPI backend + Next.js frontend (static export) for browsing PO history and bin inventory,
served from Replit and backed by Neon Postgres.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, psycopg (psycopg3), uvicorn |
| Frontend | Next.js 15 (static export), React 19, AG Grid |
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
cd next-ui && npm run dev  # optional; workflow serves the built export
```

### Production-style (API serves built UI)
```
npm ci --prefix next-ui && npm run build --prefix next-ui
uvicorn po_api:app --host 0.0.0.0 --port 5000
```

## Required secrets (Replit Secrets pane)

| Secret | Description |
|---|---|
| `NEON_DATABASE_URL` | Neon **pooled** connection string (`DATABASE_URL` is reserved by Replit). App forces `sslmode=require` and `dbname=neondb` (override with `NEON_DATABASE`); tables live in the `po_history` schema (search_path set per connection — Neon's pooler rejects it as a startup option) |
| `CLERK_SECRET_KEY` | Auto-provisioned by Replit-managed Clerk |
| `CLERK_PUBLISHABLE_KEY` | Auto-provisioned by Replit-managed Clerk |
| `VITE_CLERK_PUBLISHABLE_KEY` | Auto-provisioned; needed at `npm run build` time (mapped to NEXT_PUBLIC_ in next.config.mjs) |
| `CLERK_JWT_KEY` | Optional PEM public key → networkless JWT verification (falls back to JWKS via secret key) |
| `APP_ORIGIN` | Optional deployment URL — pins `authorized_parties` (azp) in production |
| `ALLOWED_EMAIL_DOMAIN` | Email domain gate, defaults to `colonydisplay.com` (backend enforces 403 for others) |
| `ENABLE_SCRIPT_RUNNER` | Set to `0` — script runner is disabled on Replit |

`NEON_DATABASE_URL` must be set before the API will serve data. The app starts
without it but returns 503 on every data endpoint.

## Project layout

```
po_api.py          FastAPI app (Postgres-backed)
next-ui/           Next.js app (output: "export" -> next-ui/out, served by FastAPI)
  src/components/api.js  Fetch helpers (all relative URLs, no hardcoded host)
neon-schema.sql    Postgres DDL — provisioned by powerbi-vm
requirements.txt   Python dependencies
handoff-replit.md  Full build checklist for this Replit track
CLERK_M365_AUTH_PLAN.md  Auth design doc
```

## What's done / what's next

- [x] API ported from SQLite → psycopg / Neon Postgres
- [x] Script runner gated behind `ENABLE_SCRIPT_RUNNER=0`
- [x] `/health` reports `max_order_date` and `data_age_days`
- [x] Clerk auth wired (Replit-managed Clerk): all data endpoints require a Bearer session token; `/health` + static stay public; backend enforces colonydisplay.com email domain (403 otherwise)
- [x] Next.js UI built (`next-ui/out`) and served by the API
- [ ] Microsoft EASIE connection — dashboard-side Clerk config (enterprise SSO) still to be enabled; email sign-in works meanwhile and the domain gate blocks outsiders
- [x] `NEON_DATABASE_URL` secret set — live Neon connection verified (319k+ PO rows, po_history schema)
- [ ] Remaining secrets set in Replit Secrets pane

## User preferences
