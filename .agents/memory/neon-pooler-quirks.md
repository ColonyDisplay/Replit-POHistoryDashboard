---
name: Neon pooled connections
description: Durable decisions for connecting this app to Neon Postgres via the pooled (PgBouncer) endpoint.
---

- Neon's pooled endpoint rejects `search_path` (and other `options`) as startup parameters — set session state after connect instead.
  **Why:** pooled connections failed with "unsupported startup parameter in options" until the parameter was moved out of the startup packet.
  **How to apply:** never pass startup `options` to a `-pooler` Neon host; configure the session post-connect.
- Use `NEON_DATABASE_URL` for the external Neon DB — Replit reserves `DATABASE_URL` (runtime-managed) for its own managed Postgres, which points at an empty local DB.
