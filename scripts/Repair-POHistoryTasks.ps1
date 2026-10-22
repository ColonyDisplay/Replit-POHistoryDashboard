#Requires -RunAsAdministrator
param(
    [System.Management.Automation.PSCredential]$Credential,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$taskPath = '\Colony\'
$userId = 'COLONYDISPLAY\reportpbi-t2'
$logDir = Join-Path $projectDir 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path $logDir "task-repair_$stamp.log"
$statusFile = Join-Path $logDir 'task-repair-status.json'
$tasks = @(
    @{ Name = 'PO History - Daily Inventory Sync'; Script = 'Run-BinInv-Sync.ps1' },
    @{ Name = 'PO History - Weekly PO+Inventory Sync'; Script = 'Run-PODetail-Report.ps1' }
)

function Write-RepairStatus([string]$Phase, [string]$Message) {
    $line = '{0:o} {1}: {2}' -f (Get-Date), $Phase, $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding utf8
    Write-Host $line
    [pscustomobject]@{ UpdatedAt = (Get-Date -Format o); Phase = $Phase; Message = $Message } |
        ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding utf8
}

try {
    foreach ($item in $tasks) {
        $runner = Join-Path $projectDir $item.Script
        if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Missing runner: $runner" }
        $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $item.Name
        if ($task.State -eq 'Running') { throw "Task already running: $($item.Name). Wait for it to finish before repair." }
        if ($task.Principal.LogonType -ne 'Password') { throw "Expected Password login on $($item.Name)" }
        $taskUser = $task.Principal.UserId
        if ($taskUser -ine $userId -and $taskUser -ine 'reportpbi-t2') {
            throw "Unexpected task account on $($item.Name): $taskUser"
        }
        $backup = Join-Path $logDir ("task-before-repair_{0}_{1}.xml" -f $stamp, $item.Script)
        Export-ScheduledTask -TaskPath $taskPath -TaskName $item.Name |
            Set-Content -LiteralPath $backup -Encoding utf8
    }

    Write-RepairStatus 'AwaitingCredentials' 'Enter the Windows password in the local credential prompt. Existing schedules will be preserved.'
    if (-not $Credential) {
        $Credential = Get-Credential -UserName $userId -Message 'Windows password for the two PO History scheduled tasks (not a PIN)'
    }
    if (-not $Credential) { throw 'Credential prompt cancelled.' }
    if ($Credential.UserName -ine $userId) { throw "Use $userId for the existing DPAPI credential files." }

    foreach ($item in $tasks) {
        $runner = Join-Path $projectDir $item.Script
        $action = New-ScheduledTaskAction `
            -Execute (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') `
            -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" `
            -WorkingDirectory $projectDir
        Set-ScheduledTask -TaskPath $taskPath -TaskName $item.Name -Action $action `
            -User $userId -Password ($Credential.GetNetworkCredential().Password) -ErrorAction Stop | Out-Null
        $saved = Get-ScheduledTask -TaskPath $taskPath -TaskName $item.Name
        if ($saved.Actions.Count -ne 1 -or $saved.Actions[0].Execute -ine $action.Execute -or
            $saved.Actions[0].Arguments -cne $action.Arguments -or
            $saved.Actions[0].WorkingDirectory -ine $projectDir -or $saved.Principal.LogonType -ne 'Password') {
            throw "Task verification failed: $($item.Name)"
        }
        Write-RepairStatus 'Repaired' "$($item.Name): PowerShell action saved; existing schedule and password login retained."
    }
    $Credential = $null

    if ($RunTests) {
        foreach ($item in $tasks) {
            Write-RepairStatus 'Testing' $item.Name
            $previousRun = (Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $item.Name).LastRunTime
            Start-ScheduledTask -TaskPath $taskPath -TaskName $item.Name
            $deadline = (Get-Date).AddMinutes(15)
            do {
                Start-Sleep -Seconds 3
                $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $item.Name
                $info = $task | Get-ScheduledTaskInfo
                if ((Get-Date) -gt $deadline) { throw "Timed out waiting for $($item.Name); the task has been left running." }
            } while ($info.LastRunTime -le $previousRun -or $task.State -eq 'Running')
            if ($info.LastTaskResult -ne 0) {
                throw ('{0} failed its scheduled test: 0x{1:X8}' -f $item.Name, [uint32]$info.LastTaskResult)
            }
            Write-RepairStatus 'TestPassed' "$($item.Name): Task Scheduler result 0."
        }
    }
    Write-RepairStatus 'Complete' 'Both PO History task actions repaired. Requested scheduled tests passed.'
} catch {
    Write-RepairStatus 'Failed' $_.Exception.Message
    throw
} finally {
    $Credential = $null
}
