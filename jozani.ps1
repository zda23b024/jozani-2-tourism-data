param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("booking", "tripadvisor", "all")]
    [string]$Source,

    [Parameter(Position = 1, Mandatory = $true)]
    [ValidateSet("catalog", "reviews", "all")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"

docker compose up -d db | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "PostgreSQL failed to start."
    exit 1
}

function Invoke-Collector([string]$SelectedSource, [string]$Service, [bool]$ExposeBrowser) {
    if ($ExposeBrowser) {
        docker compose run --quiet-pull --service-ports --rm --no-deps $Service python main.py $SelectedSource $Mode
    } else {
        docker compose run --quiet-pull --rm --no-deps $Service python main.py $SelectedSource $Mode
    }
    $script:CollectorExitCode = $LASTEXITCODE
}

if ($Source -eq "all") {
    Invoke-Collector "booking" "booking-browser" $true
    $bookingStatus = $script:CollectorExitCode
    Invoke-Collector "tripadvisor" "app" $false
    $tripadvisorStatus = $script:CollectorExitCode

    Write-Output ""
    if ($bookingStatus -eq 0) { Write-Output "Booking.com     SUCCESS" } else { Write-Output "Booking.com     FAILED" }
    if ($tripadvisorStatus -eq 0) { Write-Output "Tripadvisor     SUCCESS" } else { Write-Output "Tripadvisor     FAILED" }
    if ($bookingStatus -eq 0 -and $tripadvisorStatus -eq 0) {
        Write-Output "Overall         SUCCESS"
        exit 0
    }
    Write-Output "Overall         FAILED"
    exit 1
}

if ($Source -eq "booking") {
    Invoke-Collector "booking" "booking-browser" $true
    exit $script:CollectorExitCode
}
Invoke-Collector "tripadvisor" "app" $false
exit $script:CollectorExitCode
