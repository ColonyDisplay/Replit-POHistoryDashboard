---
name: Neon connection quirks
description: How this app must connect to Neon Postgres (pooler limits, schema, env var naming)
---

- Neon's pooled (PgBouncer) endpoint **rejects `options=-c search_path=...`** as a startup parameter. Set search_path per connection instead (psycopg_pool `configure=` hook running `SET search_path TO po_history, public`).
- App tables (`po_detail`, `bin_inventory`, `run_log`, `inv_run_log`) live in the **`po_history` schema**, not `public`, in the Neon project "Colony-estimates" (database `neondb`).
- `DATABASE_URL` is a Replit runtime-managed key — the app reads **`NEON_DATABASE_URL`** instead (fallback to `DATABASE_URL`).
- User-pasted connection strings have been wrong before (pointed at nonexistent `heliumdb`, missing sslmode). The pool passes `sslmode=require` and `dbname` (env `NEON_DATABASE`, default `neondb`) as connect kwargs, which override the conninfo string.

**Why:** each of these caused a real outage/500 during initial Neon hookup (Aug 2026).
**How to apply:** any code that opens its own Postgres connection to Neon must replicate the search_path + sslmode + dbname handling in `po_api.py`'s `get_pool()`.
