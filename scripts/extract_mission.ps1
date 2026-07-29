param (
    [Parameter(Mandatory=$true)]
    [string]$MissionFile,
    [string]$MissionName
)

$ConfigPath = Join-Path $PSScriptRoot "..\config.json"
if (-not (Test-Path $ConfigPath)) {
    Write-Error "Could not find config.json at $ConfigPath"
    exit
}

$config = Get-Content $ConfigPath | ConvertFrom-Json
$ExportsDir = $config.exports_dir

if (-not $ExportsDir) {
    Write-Error "exports_dir not set in config.json"
    exit
}

if (-not (Test-Path $MissionFile)) {
    Write-Error "Mission file not found: $MissionFile"
    exit
}

if (-not $MissionName) {
    $MissionName = [System.IO.Path]::GetFileNameWithoutExtension($MissionFile)
}

$OutputDir = Join-Path $ExportsDir ($MissionName + "_SQM")

if (-not (Test-Path $ExportsDir)) {
    New-Item -ItemType Directory -Path $ExportsDir -Force | Out-Null
}

$ParserScript = Join-Path $PSScriptRoot "parse_sqm.py"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "        EXTRACTING ARMA 3 MISSION ($MissionName)" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Source: $MissionFile"
Write-Host "Output: $OutputDir"

python $ParserScript $MissionFile $OutputDir

if ($LASTEXITCODE -eq 0) {
    Write-Host "Mission extraction complete!" -ForegroundColor Green
} else {
    Write-Error "Mission extraction failed!"
}