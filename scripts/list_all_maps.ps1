$ConfigPath = Join-Path $PSScriptRoot "..\config.json"
if (-not (Test-Path $ConfigPath)) {
    Write-Error "Could not find config.json at $ConfigPath"
    exit
}

$config = Get-Content $ConfigPath | ConvertFrom-Json
$Arma3Dir = $config.arma3_dir
$WorkshopDir = $config.workshop_dir

$WrpAnalyzerDir = Join-Path $PSScriptRoot "WrpAnalyzer"

Set-Location $WrpAnalyzerDir

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "        LISTING ARMA 3 BASE MAPS              " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# Run for base Arma 3 directory
dotnet run -c Release -- list_maps "`"$Arma3Dir`""

if ($WorkshopDir -and (Test-Path $WorkshopDir)) {
    Write-Host "`n==============================================" -ForegroundColor Cyan
    Write-Host "        LISTING WORKSHOP MAPS                 " -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor Cyan
    dotnet run -c Release -- list_maps "`"$WorkshopDir`""
}

Set-Location $PSScriptRoot
Write-Host "`nMap listing complete!" -ForegroundColor Green
