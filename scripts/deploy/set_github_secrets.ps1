# Set every GitHub Actions secret the CD deploy needs, in one go. Values are generated or typed here and sent straight to
# GitHub with `gh secret set`; nothing is printed, written to disk or committed.
#   .\scripts\deploy\set_github_secrets.ps1 -DeployHost 54.79.250.93
# Asks for: your Gmail address (alert sender/recipient, Let's Encrypt contact) and the Gmail App Password (hidden input).
param(
    [Parameter(Mandatory = $true)][string]$DeployHost,
    [string]$Domain = "veena-flare.duckdns.org",
    [string]$DeployUser = "ubuntu",
    [string]$KeyPath = "\\wsl.localhost\Ubuntu\home\veena\.ssh\flare_deploy",
    [string]$Repo = "veenaphadtare12-ux/aditya-l1-solar-flare-nowcasting-forecasting"
)
$ErrorActionPreference = "Stop"

function Set-Secret([string]$Name, [string]$Value) {
    $Value | gh secret set $Name --repo $Repo
    if ($LASTEXITCODE -ne 0) { throw "could not set $Name" }
    Write-Host "  set $Name"
}
function New-RandomSecret([int]$Bytes) {
    $b = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return [Convert]::ToBase64String($b).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if (-not (Test-Path $KeyPath)) { throw "deploy key not found at $KeyPath" }
$gmail = Read-Host "Gmail address (alerts are sent from and to it)"
if ($gmail -notmatch '^[^@\s]+@gmail\.com$') { throw "that does not look like a Gmail address" }
$sec = Read-Host "Gmail App Password (16 letters; input is hidden)" -AsSecureString
$app = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
if (($app -replace '\s', '').Length -ne 16) { throw "an App Password has 16 letters (spaces are ignored)" }

Write-Host "Setting secrets in $Repo ..."
Set-Secret DEPLOY_HOST $DeployHost
Set-Secret DEPLOY_USER $DeployUser
Set-Secret DEPLOY_SSH_KEY ((Get-Content $KeyPath -Raw).TrimEnd() + "`n")
Set-Secret SITE_ADDRESS $Domain
Set-Secret ACME_EMAIL $gmail
Set-Secret FLARE_API_KEYS (New-RandomSecret 32)
Set-Secret GRAFANA_ADMIN_PASSWORD (New-RandomSecret 18)
Set-Secret SMTP_SMARTHOST "smtp.gmail.com:587"
Set-Secret SMTP_USERNAME $gmail
Set-Secret SMTP_FROM $gmail
Set-Secret ALERT_EMAIL_TO $gmail
Set-Secret SMTP_PASSWORD ($app -replace '\s', '')
$app = $null
Write-Host "Done. Secret names now in the repository:"
gh secret list --repo $Repo --json name --jq '.[].name'
