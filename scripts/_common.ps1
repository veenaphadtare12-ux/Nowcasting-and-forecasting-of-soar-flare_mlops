# Shared helpers for the scripts in this folder (Windows PowerShell 5.1 and PowerShell 7).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Get-FlareTag {
    $sha = (git rev-parse --short=12 HEAD).Trim()
    if (git status --porcelain --untracked-files=no) { $sha = "$sha-dirty" }
    return $sha
}

function Wait-Http([string]$Url, [int]$TimeoutSec = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 3 }
    }
    throw "timeout waiting for $Url"
}

function Assert-Docker {
    docker version --format "{{.Server.Version}}" *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker engine is not running: start Docker Desktop and retry." }
}
