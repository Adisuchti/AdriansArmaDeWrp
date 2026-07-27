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

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "        VOXELIZING ARMA 3 MODELS ($MapName)   " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

dotnet run -c Release -- voxelize "`"$Arma3Dir`"" "`"$ExportsDir`"" "`"$MapName`""

Set-Location $PSScriptRoot
Write-Host "`nVoxelization complete! Models have been generated in the web folder." -ForegroundColor Green
