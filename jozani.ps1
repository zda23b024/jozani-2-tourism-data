param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("booking", "tripadvisor", "all")]
    [string]$Source,

    [Parameter(Position = 1, Mandatory = $true)]
    [ValidateSet("catalog", "reviews", "all")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Main = Join-Path $ProjectRoot "main.py"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Local virtual environment was not found. Create it with: python -m venv .venv"
    exit 1
}

if (-not (Test-Path -LiteralPath $Main)) {
    Write-Error "main.py was not found at expected path: $Main"
    exit 1
}

$SourceArg = if ($Source -eq "all") { "both" } else { $Source }
$ModeFlag = switch ($Mode) {
    "catalog" { "--catalog" }
    "reviews" { "--reviews" }
    "all" { "--all" }
}

Push-Location $ProjectRoot
try {
    & $Python $Main $ModeFlag --source $SourceArg
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
