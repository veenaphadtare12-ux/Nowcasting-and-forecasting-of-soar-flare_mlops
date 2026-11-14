# Restore volumes from a backup folder (runs scripts/restore.sh on the Docker host).
#   .\scripts\restore.ps1 -From D:\backups\flare\20261114T120000Z                 live volumes (stop the stack first)
#   .\scripts\restore.ps1 -From <folder> -Volumes mlflow,grafana                  only some volumes
#   .\scripts\restore.ps1 -From <folder> -Prefix flare_restoretest                into new volumes, for a restore test
param([Parameter(Mandatory = $true)][string]$From, [string[]]$Volumes = @(), [string]$Prefix = "flare")
. "$PSScriptRoot\_common.ps1"
$vols = ($Volumes -join " ")
Invoke-Bash "RESTORE_PREFIX=$Prefix bash scripts/restore.sh '$((Get-WslPath $From))' $vols"
