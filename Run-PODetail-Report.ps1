$credScript = "C:\VSCode_Projects\Credential Helper\Epicor-Cred.ps1"
. $credScript

pip install -r "$PSScriptRoot\requirements.txt" --quiet

$cred = Get-EpicorCredential
$env:EPICOR_USER = $cred.UserName
$env:EPICOR_PASS = $cred.GetNetworkCredential().Password

try {
    python -u "$PSScriptRoot\po_detail_report.py" @args

    # Also sync inventory (bin_inventory.db) unless a specific mode was passed
    if ($args -notcontains "--backfill-buyers") {
        Write-Host ""
        Write-Host "Running inventory sync..." -ForegroundColor Cyan
        python -u "$PSScriptRoot\bin_inv_sync.py"
    }
} finally {
    $env:EPICOR_USER = $null
    $env:EPICOR_PASS = $null
}
