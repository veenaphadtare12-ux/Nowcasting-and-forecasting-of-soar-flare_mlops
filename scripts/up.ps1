# Build the images (tagged with the git SHA) and start the whole product with Docker Compose.
#   .\scripts\up.ps1                  build + start + smoke test, then delete older flare image tags
#   .\scripts\up.ps1 -NoBuild         start the existing images for the current commit
#   .\scripts\up.ps1 -Tag <sha>       start a specific existing image tag (no build)
#   .\scripts\up.ps1 -KeepOldImages   do not delete older flare image tags
# Disk rule: the BuildKit cache is kept (a code-only rebuild then costs almost nothing). Older flare image tags are
# deleted only after the new stack started AND the smoke test passed, so a failed release keeps the previous image.
param([switch]$NoBuild, [string]$Tag = "", [switch]$KeepOldImages)
. "$PSScriptRoot\_common.ps1"
$tag = if ($Tag) { $Tag } else { Get-FlareTag }
Write-Host "FLARE_TAG = $tag  (docker: $(if ($script:Native) {'native'} else {"WSL $Distro"}))"
if (-not $NoBuild -and -not $Tag) { Invoke-Bash "FLARE_TAG=$tag docker compose build api frontend" }
# A local API key for POST /predict lives only in the uncommitted .env (generated once, never printed).
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile) -or -not (Select-String -Path $envFile -Pattern '^FLARE_API_KEYS=.+' -Quiet)) {
    $bytes = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $key = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $lines = if (Test-Path $envFile) { @(Get-Content $envFile | Where-Object { $_ -notmatch '^FLARE_API_KEYS=' }) } else { @() }
    [IO.File]::WriteAllText($envFile, ((@($lines) + "FLARE_API_KEYS=$key") -join "`n") + "`n")
    Write-Host "generated a local API key in .env (FLARE_API_KEYS)"
}
Invoke-Bash "FLARE_TAG=$tag docker compose up -d --pull missing"
Wait-Http "http://localhost:8000/health" 240 | Out-Null
Wait-Http "http://localhost:8080/" 120 | Out-Null

& "$PSScriptRoot\smoke_test.ps1"
if ($LASTEXITCODE -ne 0) { throw "smoke test failed: older images are kept for a rollback (.\scripts\up.ps1 -Tag <old sha>)" }

if (-not $KeepOldImages) {
    $repo = "ghcr.io/veenaphadtare12-ux"
    Invoke-Bash ("for img in flare-api flare-frontend; do docker images $repo/`$img --format '{{.Tag}}' | grep -vx '$tag' | " +
        "while read t; do docker rmi $repo/`$img:`$t >/dev/null && echo removed $repo/`$img:`$t; done; done; true")
}
Write-Host ""
Write-Host "Website     http://localhost:8080      (via Caddy: http://localhost)"
Write-Host "API docs    http://localhost:8000/docs"
Write-Host "Grafana     http://localhost:3000"
Write-Host "Prometheus  http://localhost:9090"
Write-Host "Alerts      http://localhost:9093      (Alertmanager)"
Write-Host "MLflow      http://localhost:5000"
Write-Host "Prefect     http://localhost:4200"
