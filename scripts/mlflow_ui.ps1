# Open the project's full MLflow history (767 runs, 9 experiments, registry with lineage tags) in the browser.
#   .\scripts\mlflow_ui.ps1            -> http://127.0.0.1:5001   (Ctrl+C to stop)
# It serves a COPY of mlflow.db, so browsing can never change the real registry. Artifacts (plots, models) are read from
# mlruns/ in place. Port 5001 because the Docker stack's MLflow (registry only) already uses 5000.
param([int]$Port = 5001)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$copy = Join-Path $env:TEMP "flare_mlflow_view.db"
Copy-Item (Join-Path $Root "mlflow.db") $copy -Force
$env:MLFLOW_DISABLE_AGENT_HINT = "1"
Write-Host "MLflow (read-only copy of mlflow.db) on http://127.0.0.1:$Port  -  Ctrl+C to stop"
& (Join-Path $Root ".venv\Scripts\mlflow.exe") ui --backend-store-uri "sqlite:///$($copy -replace '\\','/')" --host 127.0.0.1 --port $Port
