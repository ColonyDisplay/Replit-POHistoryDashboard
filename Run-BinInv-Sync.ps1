# PO History - Bin Inventory sync runner.
# Loads Epicor credentials and the Neon DATABASE_URL from DPAPI-protected files
# in the user profile (so scheduled tasks work with no interactive session),
# logs each run for debuggability, and propagates the Python exit code so Task
# Scheduler reports real success/failure instead of a misleading 0.

$logDir = Join-Path $PSScriptRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ('bininv_{0:yyyyMMdd_HHmmss}.log' -f (Get-Date))
Start-Transcript -Path $logFile | Out-Null

$exitCode    = 1
$dbUrlWasSet = [bool]$env:DATABASE_URL
try {
    # --- Epicor credentials: prefer DPAPI-protected files, fall back to the
    #     Credential Helper repo when present. ---
    $epUserFile = "$env:USERPROFILE\Epicor_user.txt"
    $epPwdFile  = "$env:USERPROFILE\Epicor_pwd.txt"
    if ((Test-Path $epUserFile) -and (Test-Path $epPwdFile)) {
        $env:EPICOR_USER = (Get-Content $epUserFile -Raw).Trim()
        $sec  = Get-Content $epPwdFile -ErrorAction Stop | ConvertTo-SecureString -ErrorAction Stop
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        $env:EPICOR_PASS = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    } else {
        $credScript = "C:\Users\reportpbi-t2\Projects\Credential-Helper\Epicor-Cred.ps1"
        if (-not (Test-Path $credScript)) { $credScript = "C:\VSCode_Projects\Credential Helper\Epicor-Cred.ps1" }
        . $credScript
        $cred = Get-EpicorCredential
        $env:EPICOR_USER = $cred.UserName
        $env:EPICOR_PASS = $cred.GetNetworkCredential().Password
    }

    # --- Neon connection: DATABASE_URL from the environment, else the
    #     DPAPI-encrypted file created by Set-NeonDatabaseUrl.ps1. ---
    if (-not $env:DATABASE_URL) {
        $neonFile = "$env:USERPROFILE\Neon_DatabaseUrl.txt"
        if (Test-Path $neonFile) {
            $sec  = Get-Content $neonFile -ErrorAction Stop | ConvertTo-SecureString -ErrorAction Stop
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
            $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        } else {
            Write-Host "DATABASE_URL not set and $neonFile not found - writing to local SQLite only."
        }
    }

    # --- Python ---
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }
    & $python -m pip install -r "$PSScriptRoot\requirements.txt" --quiet
    & $python -u "$PSScriptRoot\bin_inv_sync.py" @args
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "RUNNER ERROR: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    $env:EPICOR_USER = $null
    $env:EPICOR_PASS = $null
    if (-not $dbUrlWasSet) { $env:DATABASE_URL = $null }
    Stop-Transcript | Out-Null
}
exit $exitCode
