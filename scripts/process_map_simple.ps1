param (
    [Parameter(Mandatory=$true)]
    [string]$MapName
)

$ConfigPath = Join-Path $PSScriptRoot "..\config.json"
if (-not (Test-Path $ConfigPath)) {
    Write-Error "Could not find config.json at $ConfigPath"
    exit
}

$config = Get-Content $ConfigPath | ConvertFrom-Json
$Arma3Dir = $config.arma3_dir
$ExportsDir = $config.exports_dir

$WrpAnalyzerDir = Join-Path $PSScriptRoot "WrpAnalyzer"

Set-Location $WrpAnalyzerDir
$WorkshopDir = $config.workshop_dir

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "  CALCULATING PHYSICAL DIMENSIONS FOR MODELS ($MapName)  " -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan

if ($WorkshopDir) {
    dotnet run -c Release -- calc_dims "`"$Arma3Dir`"" "`"$ExportsDir`"" "`"$MapName`"" "`"$WorkshopDir`""
} else {
    dotnet run -c Release -- calc_dims "`"$Arma3Dir`"" "`"$ExportsDir`"" "`"$MapName`""
}

Set-Location $PSScriptRoot
Write-Host "`nDimension calculation complete! Perfectly sized bounding boxes are ready." -ForegroundColor Green
