# Build the images (tagged with the git SHA) and start the whole product with Docker Compose.
#   .\scripts\up.ps1            build + start
#   .\scripts\up.ps1 -NoBuild   start the existing images
param([switch]$NoBuild)
. "$PSScriptRoot\_common.ps1"
$tag = Get-FlareTag
Write-Host "FLARE_TAG = $tag  (docker: $(if ($script:Native) {'native'} else {"WSL $Distro"}))"
if (-not $NoBuild) {
    Invoke-Bash "FLARE_TAG=$tag docker compose build api frontend"
    Invoke-Bash "docker builder prune -f >/dev/null"   # disk rule: never keep build cache (the WSL disk does not shrink)
}
Invoke-Bash "FLARE_TAG=$tag docker compose up -d"
Wait-Http "http://localhost:8000/health" 240 | Out-Null
Wait-Http "http://localhost:8080/" 120 | Out-Null
Write-Host ""
Write-Host "Frontend    http://localhost:8080"
Write-Host "API docs    http://localhost:8000/docs"
Write-Host "Grafana     http://localhost:3000   (admin / GRAFANA_ADMIN_PASSWORD, default admin)"
Write-Host "Prometheus  http://localhost:9090"
Write-Host "MLflow      http://localhost:5000"
Write-Host "Prefect     http://localhost:4200"
