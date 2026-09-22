---
name: Neon connection quirks
description: How this app must connect to Neon Postgres (pooler limits, schema, env var naming)
---

- Neon's pooled (PgBouncer) endpoint **rejects `options=-c search_path=...`** as a startup parameter. Set search_path per connection instead (psycopg_pool `configure=` hook running `SET search_path TO po_history, public`).
- App tables (`po_detail`, `bin_inventory`, `run_log`, `inv_run_log`) live in the **`po_history` schema**, not `public`, in the Neon project "Colony-estimates" (database `neondb`).
- `DATABASE_URL` is a Replit runtime-managed key — the app reads **`NEON_DATABASE_URL`** instead (fallback to `DATABASE_URL`).
- User-pasted connection strings have been wrong before (pointed at nonexistent `heliumdb`, missing sslmode). The pool passes `sslmode=require` and `dbname` (env `NEON_DATABASE`, default `neondb`) as connect kwargs, which override the conninfo string.
- Long-running VM processes must health-check pooled connections on checkout. Neon can close an idle connection while it remains queued, causing an intermittent first-request 500 unless the pool discards it before use.

**Why:** these issues caused real production outages, including an intermittent `/me` failure after VM idle time.
**How to apply:** any Neon connection pool must preserve the schema/TLS/database settings and validate each connection before handing it to a request.
