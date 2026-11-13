# Stop the product. -Volumes also deletes the predictions store volume.
param([switch]$Volumes)
. "$PSScriptRoot\_common.ps1"
if ($Volumes) { docker compose --profile tools down --volumes } else { docker compose --profile tools down }
