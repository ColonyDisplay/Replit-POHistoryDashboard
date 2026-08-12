# Credential Helper: prefer the cloned repo on this machine, fall back to the
# legacy path convention (see handoff-powerbi.md "Machine Prerequisites").
$credScript = "C:\Users\reportpbi-t2\Projects\Credential-Helper\Epicor-Cred.ps1"
if (-not (Test-Path $credScript)) {
    $credScript = "C:\VSCode_Projects\Credential Helper\Epicor-Cred.ps1"
}
. $credScript

# Use the repo venv when present, otherwise whatever python is on PATH
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python -m pip install -r "$PSScriptRoot\requirements.txt" --quiet

$cred = Get-EpicorCredential
$env:EPICOR_USER = $cred.UserName
$env:EPICOR_PASS = $cred.GetNetworkCredential().Password

# Neon connection: use DATABASE_URL from the environment if set, otherwise
# load the DPAPI-encrypted file created by Set-NeonDatabaseUrl.ps1.
$dbUrlWasSet = [bool]$env:DATABASE_URL
if (-not $env:DATABASE_URL) {
    $neonFile = "$env:USERPROFILE\Neon_DatabaseUrl.txt"
    if (Test-Path $neonFile) {
        $sec  = Get-Content $neonFile | ConvertTo-SecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    } else {
        Write-Host "DATABASE_URL not set and $neonFile not found - writing to local SQLite only." -ForegroundColor Yellow
    }
}

try {
    & $python -u "$PSScriptRoot\bin_inv_sync.py" @args
} finally {
    $env:EPICOR_USER = $null
    $env:EPICOR_PASS = $null
    if (-not $dbUrlWasSet) { $env:DATABASE_URL = $null }
}
