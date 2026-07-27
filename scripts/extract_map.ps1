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
$WorkshopDir = $config.workshop_dir
$ExportsDir = $config.exports_dir

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
Write-Host "        EXTRACTING ARMA 3 MAP ($MapName)      " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# Run for base Arma 3 directory
dotnet run -c Release -- extract_single "`"$Arma3Dir`"" "`"$RawDataDir`"" "`"$ExportsDir`"" "`"$MapName`""

if ($WorkshopDir -and (Test-Path $WorkshopDir)) {
    dotnet run -c Release -- extract_single "`"$WorkshopDir`"" "`"$RawDataDir`"" "`"$ExportsDir`"" "`"$MapName`""
}

Set-Location $PSScriptRoot
Write-Host "`nMap extraction complete!" -ForegroundColor Green
