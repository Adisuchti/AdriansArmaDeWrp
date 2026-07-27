$ConfigPath = Join-Path $PSScriptRoot "..\config.json"
if (-not (Test-Path $ConfigPath)) {
    Write-Error "Could not find config.json at $ConfigPath"
    exit
}

$config = Get-Content $ConfigPath | ConvertFrom-Json
$Arma3Dir = $config.arma3_dir
$WorkshopDir = $config.workshop_dir
$ExportsDir = $config.exports_dir

# Combine base game and workshop directories for processing if needed, 
# but WrpAnalyzer currently takes a single directory. We'll run it twice if WorkshopDir exists.

$WrpAnalyzerDir = Join-Path $PSScriptRoot "WrpAnalyzer"
$RawDataDir = Join-Path $PSScriptRoot "extracted_raw_data"

if (-not (Test-Path $RawDataDir)) {
    New-Item -ItemType Directory -Path $RawDataDir -Force | Out-Null
}

if (-not (Test-Path $ExportsDir)) {
    New-Item -ItemType Directory -Path $ExportsDir -Force | Out-Null
}

Set-Location $WrpAnalyzerDir

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "        EXTRACTING ARMA 3 BASE MAPS           " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# Run for base Arma 3 directory
dotnet run -c Release -- "`"$Arma3Dir`"" "`"$RawDataDir`"" "`"$ExportsDir`""

if ($WorkshopDir -and (Test-Path $WorkshopDir)) {
    Write-Host "`n==============================================" -ForegroundColor Cyan
    Write-Host "        EXTRACTING WORKSHOP MAPS              " -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor Cyan
    dotnet run -c Release -- "`"$WorkshopDir`"" "`"$RawDataDir`"" "`"$ExportsDir`""
}

Set-Location $PSScriptRoot
Write-Host "`nMap extraction complete! You can now run process_all_maps.ps1 to convert models." -ForegroundColor Green
