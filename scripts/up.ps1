# Build the images (tagged with the git SHA) and start the whole product with Docker Compose.
#   .\scripts\up.ps1            build + start
#   .\scripts\up.ps1 -NoBuild   start the existing images
param([switch]$NoBuild)
. "$PSScriptRoot\_common.ps1"
Assert-Docker
$env:FLARE_TAG = Get-FlareTag
Write-Host "FLARE_TAG = $env:FLARE_TAG"
if (-not $NoBuild) { docker compose build; if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" } }
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }
Wait-Http "http://localhost:8000/health" | Out-Null
Write-Host ""
Write-Host "API       http://localhost:8000/docs"
if (docker compose config --services | Select-String -Quiet "^frontend$") { Write-Host "Frontend  http://localhost:8080" }
if (docker compose config --services | Select-String -Quiet "^grafana$")  { Write-Host "Grafana   http://localhost:3000  (admin / admin)" }
if (docker compose config --services | Select-String -Quiet "^prometheus$") { Write-Host "Prometheus http://localhost:9090" }
