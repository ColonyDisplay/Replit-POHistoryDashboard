$credScript = "C:\VSCode_Projects\Credential Helper\Epicor-Cred.ps1"
. $credScript

pip install -r "$PSScriptRoot\requirements.txt" --quiet

$cred = Get-EpicorCredential
$env:EPICOR_USER = $cred.UserName
$env:EPICOR_PASS = $cred.GetNetworkCredential().Password

try {
    python -u "$PSScriptRoot\bin_inv_sync.py" @args
} finally {
    $env:EPICOR_USER = $null
    $env:EPICOR_PASS = $null
}
