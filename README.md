# Replit-POHistoryDashboard

Build repo for migrating the Colony PO History dashboard to **Neon
Postgres** (data) and **Replit** (hosting), with **Clerk + Microsoft 365**
authentication. Packaged 2026-08-11 from the working project in
`ColonyDisplay/Colony-Projects` → `PO-History-Detail-SQLLite/`.

## Two Build Tracks

| Track | Where | Start here |
|---|---|---|
| Data pull + Neon provisioning | **powerbi-vm** (production integration machine) | `handoff-powerbi.md` |
| Frontend + API + Clerk/M365 auth | **Replit** | `handoff-replit.md` |

Shared dependency: one Neon Postgres database (`neon-schema.sql`), written
by powerbi-vm, read by the Replit app. The powerbi-vm track provisions it
first and hands the reader connection string to the Replit track.

## Contents

| Path | Role | Track |
|---|---|---|
| `handoff-powerbi.md` | Build instructions — data pipeline | powerbi-vm |
| `handoff-replit.md` | Build instructions — dashboard | Replit |
| `neon-schema.sql` | Postgres DDL (matches live SQLite schema) | both |
| `po_api.py` | FastAPI app (to be ported SQLite → Postgres) | Replit |
| `react-ui/` | Vite + React SPA | Replit |
| `po_detail_report.py` | PO history sync (Epicor BAQ) | powerbi-vm |
| `bin_inv_sync.py` | Bin inventory sync (Epicor BAQ) | powerbi-vm |
| `Run-PODetail-Report.ps1` | Runner — PO + inventory sync | powerbi-vm |
| `Run-BinInv-Sync.ps1` | Runner — inventory only | powerbi-vm |
| `requirements.txt` | Python dependencies | both |
| `.env.example` | Runtime env template | both |

## Planning Documents

- `REPLIT_NEON_MIGRATION_PLAN.md` — the architecture both tracks implement
- `CLERK_M365_AUTH_PLAN.md` — authentication design (Replit track)
- `PO_Detail_Architecture_Plan.md` — original design history
- `VERCEL_MIGRATION_PLAN.md` — the alternative that was not chosen

## Rules

- No secrets, databases, or workbooks in this repo (`.gitignore` enforces).
- Epicor credentials come from the Credential Helper on the Windows side.
- The legacy internal deployment (Docker in WSL) stays running as fallback
  until cutover completes — see the migration plan's Phase 6.
