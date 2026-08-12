# Stores the Neon DATABASE_URL DPAPI-encrypted in the user profile, following
# the Credential Helper pattern (see handoff-powerbi.md "Store the connection
# string"). The Run-*.ps1 runners load it automatically when DATABASE_URL is
# not already set in the environment.
#
# Usage: copy the Neon *direct* (non-pooled) writer connection string to the
# clipboard, then run:  .\Set-NeonDatabaseUrl.ps1
#
# NOTE: DPAPI encryption is bound to the Windows account that runs this
# script. Run it as the same account that will run the scheduled tasks.

$NeonUrlPath = "$env:USERPROFILE\Neon_DatabaseUrl.txt"

Write-Host "Copy the Neon DATABASE_URL (postgresql://...sslmode=require) to the clipboard, then press Enter." -ForegroundColor Yellow
$null = Read-Host -Prompt "Press Enter when ready"
$plainText = Get-Clipboard -Raw
if ([string]::IsNullOrWhiteSpace($plainText)) {
    throw "Clipboard was empty. Copy the connection string, then run the script again."
}
Set-Clipboard -Value $null

$plainText = $plainText.Trim()
if ($plainText -notmatch '^postgres(ql)?://') {
    throw "That does not look like a Postgres connection string (expected postgresql://...)."
}

ConvertTo-SecureString $plainText -AsPlainText -Force |
    ConvertFrom-SecureString |
    Set-Content -Path $NeonUrlPath -Force -Encoding UTF8

Write-Host "Neon DATABASE_URL saved (encrypted) to: $NeonUrlPath" -ForegroundColor Green
