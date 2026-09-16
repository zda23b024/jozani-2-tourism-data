$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Dashboard = Join-Path $ProjectRoot "monitoring_dashboard\app.py"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Local virtual environment was not found. Create it with: python -m venv .venv"
    exit 1
}

if (-not (Test-Path -LiteralPath $Dashboard)) {
    Write-Error "Dashboard entrypoint was not found at expected path: $Dashboard"
    exit 1
}

Push-Location $ProjectRoot
try {
    & $Python -m streamlit run $Dashboard
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
