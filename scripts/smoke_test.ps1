# Smoke test of every API endpoint (and, if given, the frontend and Prometheus). Exit code 1 on any failure.
#   .\scripts\smoke_test.ps1
#   .\scripts\smoke_test.ps1 -Api http://localhost:30080/api -Frontend http://localhost:30080      (Kubernetes)
param(
    [string]$Api = "http://localhost:8000",
    [string]$Frontend = "",
    [string]$Prometheus = ""
)
$ErrorActionPreference = "Stop"
$failed = 0
function Check([string]$Name, [scriptblock]$Test) {
    try {
        $msg = & $Test
        Write-Host ("  OK    {0,-28} {1}" -f $Name, $msg) -ForegroundColor Green
    } catch {
        Write-Host ("  FAIL  {0,-28} {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red
        $script:failed++
    }
}
function Get-Json([string]$Path) { Invoke-RestMethod -Uri "$Api$Path" -TimeoutSec 30 }

Write-Host "API $Api"
Check "GET /health" { $h = Get-Json "/health"; if ($h.status -ne "ok") { throw "status $($h.status)" }; "bundle $($h.bundle_version), image $($h.image_git_sha)" }
Check "GET /models" { $m = Get-Json "/models"; if (@($m).Count -ne 5) { throw "expected 5 models, got $(@($m).Count)" }; "5 champions" }
Check "GET /replay/days" { $d = Get-Json "/replay/days"; if (@($d).Count -lt 4) { throw "too few days" }; "$(@($d).Count) days" }
Check "GET /replay/{day}?until" {
    $r = Get-Json "/replay/2026-04-24?until=2026-04-24T09:00:00Z&step=6"
    $n = @($r.predictions.now.p_flare).Count
    if ($n -lt 10) { throw "only $n nowcast points" }
    "$n nowcast points, $(@($r.goes_flares).Count) GOES flares known, source=$($r.source)"
}
Check "GET /replay/{day}/stream" {
    $s = Invoke-WebRequest -Uri "$Api/replay/2026-02-21/stream?speed=600&step=60&start=2026-02-21T23:00:00Z" -UseBasicParsing -TimeoutSec 60
    $frames = ([regex]::Matches($s.Content, "event: frame")).Count
    if ($frames -lt 3 -or $s.Content -notmatch "event: end") { throw "frames=$frames" }
    "$frames SSE frames"
}
Check "POST /predict (feature rows)" {
    $m = Get-Json "/models" | Where-Object { $_.target -eq "c_60m" }
    $row = @{}; foreach ($f in $m.features) { $row[$f] = 0.0 }
    $body = @{ target = "c_60m"; rows = @($row) } | ConvertTo-Json -Depth 5
    $p = Invoke-RestMethod -Method Post -Uri "$Api/predict" -Body $body -ContentType "application/json"
    if ($p.p_flare[0] -lt 0 -or $p.p_flare[0] -gt 1) { throw "p out of range" }
    "p=$([math]::Round($p.p_flare[0],3)) threshold=$([math]::Round($p.threshold,3))"
}
Check "GET /results" { $r = Get-Json "/results"; if ($null -eq $r.test.targets.now.tss) { throw "no test results" }; "test nowcast TSS $([math]::Round($r.test.targets.now.tss,3))" }
Check "GET /drift/latest" { $d = Get-Json "/drift/latest"; "drifted share $([math]::Round($d.drifted_share,2)), flag=$($d.drift_flag)" }
Check "GET /pipeline/status" { $s = Get-Json "/pipeline/status"; "$($s.dvc.total) DVC stages ($($s.dvc.frozen) frozen)" }
Check "GET /metrics" { $m = (Invoke-WebRequest -Uri "$Api/metrics" -UseBasicParsing).Content; if ($m -notmatch "flare_api_requests_total") { throw "metric missing" }; "prometheus text ok" }

if ($Frontend) {
    Write-Host "Frontend $Frontend"
    Check "GET / (frontend)" { $f = Invoke-WebRequest -Uri $Frontend -UseBasicParsing -TimeoutSec 30; if ($f.Content -notmatch '<div id="root">') { throw "no app root" }; "index.html served" }
}
if ($Prometheus) {
    Write-Host "Prometheus $Prometheus"
    Check "Prometheus scrapes the API" {
        $deadline = (Get-Date).AddSeconds(60)
        do {
            $q = Invoke-RestMethod -Uri "$Prometheus/api/v1/query?query=flare_api_requests_total" -TimeoutSec 10
            if (@($q.data.result).Count -gt 0) { return "$(@($q.data.result).Count) series" }
            Start-Sleep 5
        } while ((Get-Date) -lt $deadline)
        throw "no flare_api_requests_total series in Prometheus"
    }
}
if ($failed) { Write-Host "$failed check(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "all checks passed" -ForegroundColor Green
