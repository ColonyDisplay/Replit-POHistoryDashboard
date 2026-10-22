# PO History Dashboard — Project Notes

Updated: 2026-10-22 (America/Chicago).

## Repository and architecture

- Local path: `C:\Colony_projects\Epicor-Dashboard -replit`.
- GitHub: `ColonyDisplay/Replit-POHistoryDashboard`.
- Current branch: `cursor/neon-http-sync-pipeline`.
- Windows data collection: `po_detail_report.py` and `bin_inv_sync.py`, launched
  by the matching PowerShell runners and publishing data to Neon.
- Dashboard track: `po_api.py` (FastAPI) and `react-ui/` (React/Vite), intended for
  Replit. Hosting/auth migration plans are in `REPLIT_NEON_MIGRATION_PLAN.md`,
  `CLERK_M365_AUTH_PLAN.md`, and the two track handoffs. Task success alone does
  not verify hosted deployment or authentication completion.

## Verified Windows operations

Both tasks run under `\Colony\` with password login as
`COLONYDISPLAY\reportpbi-t2`, using Windows PowerShell and machine-wide Python
3.12. Repair corrected stale script paths and direct `.ps1` launch actions.

| Task | Verified schedule | Latest test on 2026-10-22 |
| --- | --- | --- |
| PO History - Daily Inventory Sync | Daily, 6:00 AM Central | Started 12:32:05 PM; passed at 12:33:05 PM, result 0 |
| PO History - Weekly PO+Inventory Sync | Monday, 5:00 AM Central | Started 12:33:06 PM; passed at 12:35:26 PM, result 0 |

`Run-PODetail-Report.ps1` normally runs the inventory sync after PO detail.
`Run-BinInv-Sync.ps1` runs inventory alone. Runners load profile credentials and
use `C:\Colony_projects\Credential-Helper` as the helper location. Local
transcripts and repair evidence are under ignored `logs/`.

`scripts/Repair-POHistoryTasks.ps1` backs up and repairs the two task actions,
preserves schedules, and optionally tests them sequentially with `-RunTests`.
`Register-POHistoryWeekdayTask.ps1` is a separate migration utility: it registers
a combined PO+inventory job at 5:00 AM Monday–Friday, removes the two old tasks,
and starts the new job. At the verification snapshot above, the two original
tasks were still registered; verify live state before invoking either utility.

## Current operational dependency

Epicor's certificate was reported expired on 2026-10-09. `epicor_http.py` first
attempts standard TLS verification and retries with OpenSSL certificate time
checks disabled only following an expiry error for the configured Epicor host.
Other certificate checks remain enabled; the fallback disables time checks for
the certificate chain, so renewal and removal/review of this workaround remain
follow-up work. No credential material belongs in source control.

## Next work

Verify the next unattended runs, resolve the upstream Epicor certificate expiry,
and confirm the intended task schedule before consolidating jobs. Continue the
Replit/Neon dashboard and authentication track from its existing handoff, using
current implementation evidence to assess completion.
