# End-to-end test of the whole product: runs scripts/e2e.sh (the same file CI runs) on the Docker engine.
#   .\scripts\e2e.ps1               build, start, test (stack stays up)
#   .\scripts\e2e.ps1 -SkipBuild    reuse the images
#   .\scripts\e2e.ps1 -Tag <sha>     test an existing image tag (implies -SkipBuild)
#   .\scripts\e2e.ps1 -Down         stop the stack and delete its volumes afterwards
param([switch]$SkipBuild, [switch]$Down, [string]$Tag = "")
. "$PSScriptRoot\_common.ps1"
$envs = @()
if ($Tag) { $envs += "FLARE_TAG=$Tag"; $SkipBuild = $true }
if ($SkipBuild) { $envs += "E2E_SKIP_BUILD=1" }
if ($Down) { $envs += "E2E_DOWN=1" }
Invoke-Bash ("{0} bash scripts/e2e.sh" -f ($envs -join " "))
