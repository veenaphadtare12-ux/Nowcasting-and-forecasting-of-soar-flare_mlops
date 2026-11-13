# Shared helpers for the scripts in this folder (Windows PowerShell 5.1 and PowerShell 7).
# Docker runs either natively (Docker Desktop / Linux) or inside WSL Ubuntu (Docker Engine): set $env:FLARE_WSL_DISTRO
# to force WSL (default: use WSL when the Windows docker CLI cannot reach an engine).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Distro = if ($env:FLARE_WSL_DISTRO) { $env:FLARE_WSL_DISTRO } else { "Ubuntu" }

function Test-NativeDocker {
    if ($env:FLARE_WSL_DISTRO) { return $false }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    docker version --format "{{.Server.Version}}" *> $null
    return ($LASTEXITCODE -eq 0)
}
$script:Native = Test-NativeDocker

function Get-WslPath([string]$WinPath) {
    $p = $WinPath -replace '\', '/'
    if ($p -match '^([A-Za-z]):(.*)$') { return "/mnt/" + $Matches[1].ToLower() + $Matches[2] }
    return $p
}

function Start-WslKeepAlive {
    # WSL stops the Ubuntu VM (and Docker with it) a few seconds after the last wsl.exe exits; keep one idle process.
    $running = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object { $_.CommandLine -match "sleep infinity" }
    if (-not $running) {
        Start-Process -WindowStyle Hidden -FilePath wsl.exe -ArgumentList "-d", $Distro, "--", "sleep", "infinity"
        Start-Sleep -Seconds 3
    }
}

function Invoke-Bash([string]$Command) {
    # Runs a bash command in the repo root, on the machine that hosts the Docker engine.
    if ($script:Native) {
        bash -lc "cd '$((Get-WslPath $Root))' 2>/dev/null || cd '$Root'; $Command"
    } else {
        Start-WslKeepAlive
        wsl.exe -d $Distro -- bash -lc "cd '$((Get-WslPath $Root))' && $Command"
    }
    if ($LASTEXITCODE -ne 0) { throw "command failed ($LASTEXITCODE): $Command" }
}

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
