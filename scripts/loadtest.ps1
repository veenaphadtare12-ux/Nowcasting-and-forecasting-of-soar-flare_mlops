# Load test with k6 (Docker image, no install): 50 virtual users for 2 minutes against the running Compose stack.
#   .\scripts\loadtest.ps1                       defaults
#   .\scripts\loadtest.ps1 -Vus 100 -Duration 5m
# Result: reports\loadtest\<UTC timestamp>.json (p50/p95/p99, requests/s, error rate, SLO pass/fail).
param([int]$Vus = 50, [string]$Duration = "2m", [string]$BaseUrl = "http://frontend:8080/api")
. "$PSScriptRoot\_common.ps1"
$key = $env:FLARE_API_KEY
if (-not $key -and (Test-Path "$Root\.env")) {
    $line = Get-Content "$Root\.env" | Where-Object { $_ -match '^FLARE_API_KEYS=' } | Select-Object -First 1
    if ($line) { $key = ($line -replace '^FLARE_API_KEYS=', '').Split(',')[0].Trim() }
}
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
New-Item -ItemType Directory -Force -Path "$Root\reports\loadtest" | Out-Null
# the key is passed through the environment of the k6 container (-e API_KEY), never printed
$env:K6_API_KEY = $key
$env:WSLENV = (@($env:WSLENV, "K6_API_KEY/u") | Where-Object { $_ }) -join ":"   # hand the variable to WSL
Invoke-Bash ("docker run --rm --network flare_default -e API_KEY=`"`$K6_API_KEY`" -e BASE_URL=$BaseUrl -e VUS=$Vus -e DURATION=$Duration " +
    "-v `"`$PWD/loadtest:/scripts:ro`" -v `"`$PWD/reports/loadtest:/results`" grafana/k6:1.3.0 run --quiet /scripts/k6.js; " +
    "rc=`$?; mv reports/loadtest/summary.json reports/loadtest/$stamp.json 2>/dev/null; exit `$rc")
