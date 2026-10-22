# Agent instructions

Read `PROJECT.md` and `SESSION_HANDOFF.md` before changing this project.

- This directory is the standalone `ColonyDisplay/Replit-POHistoryDashboard`
  repository. Confirm the Git root and branch before committing; the parent
  `C:\Colony_projects` directory is a different repository.
- Windows collects Epicor PO detail and bin inventory and publishes to Neon.
  Replit owns the hosted dashboard track. See `handoff-powerbi.md` and
  `handoff-replit.md` for the original track plans; use current code and the
  project/session notes for verified operational status.
- Scheduled runners use `C:\Program Files\Python312\python.exe` and Windows
  PowerShell. Keep paths deterministic and propagate failures to Task Scheduler.
- Credentials come from the task account's profile using DPAPI and
  `C:\Colony_projects\Credential-Helper`. Never commit credentials, connection
  strings, local logs, task backups, databases, or workbooks.
- Before changing task registration, inspect the live actions, triggers, account,
  and last result. Task scripts require administrator rights and may prompt
  locally for credentials. Never request a password in chat.
- `Register-POHistoryWeekdayTask.ps1` replaces the two existing task definitions
  with a combined weekday job. Its presence does not establish that it has run.
- Keep Epicor TLS handling centralized in `epicor_http.py`; document the current
  certificate expiry workaround and revisit it when the upstream certificate is
  renewed. Do not expand the workaround to unrelated hosts.
- Validate Python and PowerShell syntax for changed runners; use scheduled task
  result codes and local logs as operational evidence. Record verification dates
  and limitations in `SESSION_HANDOFF.md`.
