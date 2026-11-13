# Stop the product. -Volumes also deletes the volumes (predictions store, MLflow, Prefect, Grafana, Prometheus data).
param([switch]$Volumes)
. "$PSScriptRoot\_common.ps1"
if ($Volumes) { Invoke-Bash "docker compose --profile tools down --volumes" } else { Invoke-Bash "docker compose --profile tools down" }
