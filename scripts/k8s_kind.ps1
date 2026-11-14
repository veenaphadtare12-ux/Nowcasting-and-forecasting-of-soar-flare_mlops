# Local Kubernetes (kind) from Windows: the work is done by scripts/k8s/*.sh on the Docker host (WSL Ubuntu).
#   .\scripts\k8s_kind.ps1                 create the cluster, load the current images, deploy, smoke test
#   .\scripts\k8s_kind.ps1 -Demo           ... then demonstrate a rolling update and a rollback
#   .\scripts\k8s_kind.ps1 -Down           delete the kind cluster (frees its disk space inside WSL)
#   .\scripts\k8s_kind.ps1 -Tag <sha>      use a specific image tag (default: the tag of the running Compose API)
# Needs kind and kubectl inside WSL Ubuntu (see docs/RUNBOOK.md#kubernetes-kind).
param([switch]$Demo, [switch]$Down, [string]$Tag = "")
. "$PSScriptRoot\_common.ps1"

if ($Down) { Invoke-Bash "kind delete cluster --name flare"; return }

Invoke-Bash "command -v kind >/dev/null && command -v kubectl >/dev/null || { echo 'kind/kubectl missing in WSL: see docs/RUNBOOK.md#kubernetes-kind'; exit 1; }"
if (-not $Tag) {
    $img = (Invoke-Bash "docker inspect flare-api-1 --format '{{.Config.Image}}' 2>/dev/null || true" | Select-Object -Last 1)
    $Tag = if ($img -match ':([^:]+)$') { $Matches[1] } else { Get-FlareTag }
}
Write-Host "image tag: $Tag"
Invoke-Bash "bash scripts/k8s/kind_up.sh $Tag"
if ($Demo) { Invoke-Bash "bash scripts/k8s/rollout_demo.sh http://localhost:18000" }
Write-Host ""
Write-Host "Website     http://localhost:18080"
Write-Host "API         http://localhost:18000/docs"
Write-Host "Grafana     http://localhost:13000"
Write-Host "Prometheus  http://localhost:19090"
Write-Host "Prefect     http://localhost:14200"
Write-Host "MLflow      http://localhost:15000"
