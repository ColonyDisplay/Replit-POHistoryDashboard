$ErrorActionPreference = 'Stop'

$taskPath = '\Colony\'
$taskName = 'PO History - PO+Inventory Sync'
$oldTaskNames = @(
    'PO History - Daily Inventory Sync',
    'PO History - Weekly PO+Inventory Sync'
)
$userId = 'COLONYDISPLAY\reportpbi-t2'
$runner = Join-Path $PSScriptRoot 'Run-PODetail-Report.ps1'

if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Combined runner not found: $runner"
}

$credential = Get-Credential -UserName $userId `
    -Message 'Enter the reportpbi-t2 password for the weekday PO History task.'
$passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)

try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
    $action = New-ScheduledTaskAction `
        -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
        -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At '5:00 AM'
    $principal = New-ScheduledTaskPrincipal `
        -UserId $userId `
        -LogonType Password `
        -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -RestartCount 2 `
        -RestartInterval (New-TimeSpan -Minutes 5)
    $definition = New-ScheduledTask `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description 'Synchronizes PO detail and bin inventory to Neon every weekday.'

    Register-ScheduledTask `
        -TaskPath $taskPath `
        -TaskName $taskName `
        -InputObject $definition `
        -User $userId `
        -Password $password `
        -Force | Out-Null

    $deadline = (Get-Date).AddMinutes(15)
    foreach ($oldTaskName in $oldTaskNames) {
        $oldTask = Get-ScheduledTask -TaskPath $taskPath -TaskName $oldTaskName `
            -ErrorAction SilentlyContinue
        while ($oldTask -and $oldTask.State -eq 'Running' -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            $oldTask = Get-ScheduledTask -TaskPath $taskPath -TaskName $oldTaskName
        }
        if ($oldTask -and $oldTask.State -eq 'Running') {
            throw "Timed out waiting for '$oldTaskName' to finish."
        }
        if ($oldTask) {
            Unregister-ScheduledTask -TaskPath $taskPath -TaskName $oldTaskName `
                -Confirm:$false
        }
    }

    Start-ScheduledTask -TaskPath $taskPath -TaskName $taskName
    Write-Host "Registered and started '$taskPath$taskName'."
} finally {
    $password = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr)
}
