# Back up all product volumes to D:\backups\flare\<UTC timestamp>\ (runs scripts/backup.sh on the Docker host).
#   .\scripts\backup.ps1                      default destination D:\backups\flare
#   .\scripts\backup.ps1 -Destination E:\bk   another folder
param([string]$Destination = "D:\backups\flare")
. "$PSScriptRoot\_common.ps1"
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Invoke-Bash "bash scripts/backup.sh '$((Get-WslPath $Destination))'"
