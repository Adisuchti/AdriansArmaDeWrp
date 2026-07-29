param (
    [Parameter(Mandatory=$true)]
    [string]$MissionName,
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

if (-not $ExportsDir) {
    Write-Error "exports_dir not set in config.json"
    exit
}

$MissionDir = Join-Path $ExportsDir ($MissionName + "_SQM")
$EntitiesFile = Join-Path $MissionDir "entities.json"

if (-not (Test-Path $EntitiesFile)) {
    Write-Error "Mission entities file not found: $EntitiesFile. Run extract_mission.ps1 first."
    exit
}

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "     PROCESSING MISSION MODELS ($MissionName)   " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

$WrpAnalyzerDir = Join-Path $PSScriptRoot "WrpAnalyzer"
$ModelsDir = Join-Path $ExportsDir "models"
if (-not (Test-Path $ModelsDir)) {
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
}

# --- Step 1: Match classnames to P3D filenames ---
$LookupFile = Join-Path $ExportsDir "classname_to_model.json"
$entities = Get-Content $EntitiesFile | ConvertFrom-Json

# --- Build or load classname→model mapping ---
$MatchScript = Join-Path $PSScriptRoot "match_models.py"
$needsRefresh = $true

if (Test-Path $LookupFile) {
    $lookupData = Get-Content $LookupFile | ConvertFrom-Json
    $existingCount = 0
    if ($lookupData.mapping) {
        $existingCount = ($lookupData.mapping | Get-Member -MemberType NoteProperty).Count
    }
    if ($existingCount -gt 0) {
        $needsRefresh = $false
        Write-Host ""
        Write-Host "Using cached classname→model lookup ($existingCount entries)..." -ForegroundColor Cyan
    }
}

if ($needsRefresh) {
    if (-not (Test-Path $MatchScript)) {
        Write-Error "match_models.py not found."
        exit 1
    }
    Write-Host ""
    Write-Host "Building P3D model index and matching classnames..." -ForegroundColor Cyan
    $argsList = @($MatchScript, $ExportsDir, $EntitiesFile)
    if ($Arma3Dir) { $argsList += "--armadir"; $argsList += $Arma3Dir }
    if ($WorkshopDir -and (Test-Path $WorkshopDir)) { $argsList += "--armadir"; $argsList += $WorkshopDir }
    & python $argsList
    if ($LASTEXITCODE -ne 0) { Write-Error "match_models.py failed."; exit 1 }
    $lookupData = Get-Content $LookupFile | ConvertFrom-Json
}

$mapping = if ($lookupData.mapping) { $lookupData.mapping } else { $lookupData }

# Resolve P3D filenames and collect unique models
$uniqueModels = @{}
$classToGlb = @{}  # For the frontend: classname → GLB filename
foreach ($e in $entities) {
    $typeName = $e.type
    if (-not $typeName) { continue }
    
    $p3dName = $null
    $lookupKeys = $mapping | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name
    if ($lookupKeys -contains $typeName) {
        $val = $mapping.$typeName
        if ($val -is [string] -and $val.Length -gt 0) {
            $p3dName = $val
        }
    }
    if (-not $p3dName) {
        $p3dName = ($typeName -replace '^(B_|O_|I_|C_|Land_|CUP_|CDF_|TK_GUE_|Base_)', '') + '.p3d'
    }
    $uniqueModels[$p3dName] = $true
    $classToGlb[$typeName] = $p3dName.ToLower().Replace('.p3d', '.glb')
}

# Save mapping to mission folder for the frontend
$classToGlb | ConvertTo-Json | Set-Content (Join-Path $MissionDir "class_to_glb.json")

Write-Host "Mission uses $($uniqueModels.Count) unique model types."

# --- Step 3: Check which models need processing ---
$missingModels = @()
foreach ($modelName in $uniqueModels.Keys) {
    $glbName = $modelName.ToLower().Replace(".p3d", ".glb")
    if (-not $glbName.EndsWith(".glb")) { $glbName += ".glb" }
    if (-not (Test-Path (Join-Path $ModelsDir $glbName))) {
        $missingModels += $modelName
    }
}

Write-Host "Already cached: $($uniqueModels.Count - $missingModels.Count) models"
Write-Host "Need to process: $($missingModels.Count) models"

if ($missingModels.Count -eq 0) {
    Write-Host ""
    Write-Host "All mission models are already cached!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Mission processing complete!" -ForegroundColor Green
    exit 0
}

# --- Step 4: Process missing models via WrpAnalyzer ---
$tempModelList = Join-Path $MissionDir "_models_to_process.txt"
$missingModels -join "`n" | Set-Content $tempModelList

Write-Host ""
Write-Host "Processing $($missingModels.Count) missing models..." -ForegroundColor Cyan
Write-Host "Models to process:"
foreach ($m in $missingModels) {
    Write-Host "  - $m" -ForegroundColor Gray
}

Set-Location $WrpAnalyzerDir

# Scan base game + workshop
dotnet run -c Release -- calc_models "`"$Arma3Dir`"" "`"$ExportsDir`"" "`"$tempModelList`""

if ($WorkshopDir -and (Test-Path $WorkshopDir)) {
    Write-Host "Also scanning Workshop directory..." -ForegroundColor Gray
    dotnet run -c Release -- calc_models "`"$WorkshopDir`"" "`"$ExportsDir`"" "`"$tempModelList`""
}

Set-Location $PSScriptRoot

# --- Step 5: Re-check ---
Write-Host ""
Write-Host "Re-checking model cache..." -ForegroundColor Gray
$stillMissing = @()
foreach ($modelName in $missingModels) {
    $glbName = $modelName.ToLower().Replace(".p3d", ".glb")
    if (-not $glbName.EndsWith(".glb")) { $glbName += ".glb" }
    if (-not (Test-Path (Join-Path $ModelsDir $glbName))) {
        $stillMissing += $modelName
    }
}

if ($stillMissing.Count -gt 0) {
    Write-Host "WARNING: $($stillMissing.Count) models could not be found in PBOs:" -ForegroundColor Yellow
    foreach ($m in $stillMissing) {
        Write-Host "  - $m" -ForegroundColor DarkYellow
    }
    Write-Host "These will render as colored markers in the viewer." -ForegroundColor Yellow
} else {
    Write-Host "All models have been successfully processed!" -ForegroundColor Green
}

Write-Host ""
Write-Host "Mission processing complete!" -ForegroundColor Green