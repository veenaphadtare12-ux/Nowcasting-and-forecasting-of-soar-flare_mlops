# Alert drill: trigger a Prometheus alert on purpose, wait until it is FIRING, then restore.
#   .\scripts\alert_drill.ps1 -Rule down              stop the API until FlareApiDown fires (about 2.5 min), then restart
#   .\scripts\alert_drill.ps1 -Rule errors            answer 50 % of API requests with 503 until FlareApiHighErrorRate fires
#                                                     (about 6 min: 5-min rate window + `for: 5m` overlap), then restore
#   add -KeepFiring to leave the fault in place (for screenshots) and run  .\scripts\alert_drill.ps1 -Restore  afterwards
param([ValidateSet("down", "errors")][string]$Rule = "down", [switch]$KeepFiring, [switch]$Restore, [int]$TimeoutSec = 600)
. "$PSScriptRoot\_common.ps1"
$tag = Get-FlareTag
$names = @{ down = "FlareApiDown"; errors = "FlareApiHighErrorRate" }

function Get-AlertState([string]$Name) {
    try {
        $a = (Invoke-RestMethod "http://localhost:9090/api/v1/alerts" -TimeoutSec 5).data.alerts | Where-Object { $_.labels.alertname -eq $Name }
        if ($a) { return ($a | Select-Object -First 1).state }
    } catch { }
    return "inactive"
}

function Restore-Api {
    Write-Host "restoring the API (fault injection off, container running)"
    Invoke-Bash "FLARE_TAG=$tag FLARE_FAULT_INJECT_RATE=0 docker compose up -d api"
    Wait-Http "http://localhost:8000/health" 240 | Out-Null
    Write-Host "API healthy again; the alert resolves after the next evaluations."
}

if ($Restore) { Restore-Api; return }

$name = $names[$Rule]
Write-Host "drill: $name   (before: $(Get-AlertState $name))"
$traffic = $null
if ($Rule -eq "down") {
    Invoke-Bash "docker compose stop api"
} else {
    Invoke-Bash "FLARE_TAG=$tag FLARE_FAULT_INJECT_RATE=0.5 docker compose up -d api"
    Wait-Http "http://localhost:8000/health" 240 | Out-Null
    # steady traffic so the error ratio is defined: 4 requests per second to an ordinary endpoint
    $traffic = Start-Job -ScriptBlock {
        while ($true) {
            try { Invoke-WebRequest "http://localhost:8000/models" -UseBasicParsing -TimeoutSec 5 | Out-Null } catch { }
            Start-Sleep -Milliseconds 250
        }
    }
}

$t0 = Get-Date
$deadline = $t0.AddSeconds($TimeoutSec)
$state = "inactive"
while ((Get-Date) -lt $deadline) {
    $state = Get-AlertState $name
    Write-Host ("  {0,4:N0} s  {1}" -f ((Get-Date) - $t0).TotalSeconds, $state)
    if ($state -eq "firing") { break }
    Start-Sleep -Seconds 15
}
if ($traffic -and -not $KeepFiring) { Stop-Job $traffic; Remove-Job $traffic }
if ($state -eq "firing") {
    Write-Host "OK  $name is FIRING after $([int]((Get-Date) - $t0).TotalSeconds) s  -> http://localhost:9090/alerts"
} else {
    Write-Host "FAIL  $name did not fire within $TimeoutSec s"
}
if ($KeepFiring) {
    if ($traffic) { Write-Host "traffic job $($traffic.Id) keeps running in this session; stop it with Stop-Job $($traffic.Id)" }
    Write-Host "fault left in place; restore with  .\scripts\alert_drill.ps1 -Restore"
} else {
    Restore-Api
}
if ($state -ne "firing") { exit 1 }
