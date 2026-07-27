param ()

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

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "  CALCULATING PHYSICAL DIMENSIONS FOR ALL EXPORTED MAPS  " -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan

dotnet run -c Release -- calc_all_dims "`"$Arma3Dir`"" "`"$ExportsDir`""

Set-Location $PSScriptRoot
Write-Host "`nAll dimension calculations complete!" -ForegroundColor Green
