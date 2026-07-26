param (
    [string]$MapName = "altis"
)

# Load config
$ConfigPath = Join-Path $PSScriptRoot "..\config.json"
if (Test-Path $ConfigPath) {
    $config = Get-Content $ConfigPath | ConvertFrom-Json
    $Arma3Dir = $config.arma3_dir
    $BankRevExe = $config.bankrev_exe
    $BlenderExe = $config.blender_exe
    $ExportsDir = $config.exports_dir
    $DebinarizerExe = $config.debinarizer_exe
    $WorkshopDir = $config.workshop_dir
} else {
    Write-Error "Could not find config.json at $ConfigPath"
    exit
}

# Paths
$JsonPath = Join-Path $ExportsDir "$MapName\objects.json"
if (-not (Test-Path $JsonPath)) {
    Write-Error "Could not find objects.json for map '$MapName' at $JsonPath"
    exit
}

$OutputDir = "converted_models"
$ExtractedDir = "extracted_models"
$MlodDir = "mlod_models"
$TempPboDir = "_temp_unpack"

if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }
if (-not (Test-Path $ExtractedDir)) { New-Item -ItemType Directory -Path $ExtractedDir -Force | Out-Null }
if (-not (Test-Path $MlodDir)) { New-Item -ItemType Directory -Path $MlodDir -Force | Out-Null }

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "     ARMA 3 MAP ASSET PIPELINE: $MapName      " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. Parse JSON for needed models
Write-Host "`n[1/4] Parsing map objects..." -ForegroundColor Yellow
$jsonContent = Get-Content $JsonPath -Raw | ConvertFrom-Json
$neededModels = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($obj in $jsonContent.objects) {
    if ($obj.model -and $obj.model -ne "unknown") {
        $neededModels.Add($obj.model) | Out-Null
    } elseif ($obj.p3d_path) {
        $neededModels.Add((Split-Path $obj.p3d_path -Leaf)) | Out-Null
    }
}

Write-Host "Total unique models found in map: $($neededModels.Count)"

# 2. Filter out already converted models (only keep successful ones > 2KB)
$existingGlbs = Get-ChildItem -Path $OutputDir -Filter "*.glb" -Recurse
foreach ($glb in $existingGlbs) {
    if ($glb.Length -gt 2KB) {
        $p3dName = $glb.Name -replace "\.glb$", ".p3d"
        $neededModels.Remove($p3dName) | Out-Null
    }
}

if ($neededModels.Count -eq 0) {
    Write-Host "`nAll models for $MapName are already converted!" -ForegroundColor Green
    exit
}

Write-Host "Models to extract and convert: $($neededModels.Count)" -ForegroundColor Red

# 3. Extract needed models from PBOs
Write-Host "`n[2/4] Scanning PBOs & Extracting models..." -ForegroundColor Yellow
Write-Host "Searching for PBOs in $Arma3Dir and Workshop (This may take a moment)..." -ForegroundColor Gray
$allPbos = Get-ChildItem -Path $Arma3Dir, $WorkshopDir -Filter "*.pbo" -Recurse -Force -ErrorAction SilentlyContinue

# Filter for likely map objects to speed up search
$relevantPbos = $allPbos | Where-Object { 
    $_.Name -imatch "rocks|structures|plants|buildings|roads|env|map|vegetation|clutter|houses|signs|props|cup|core|a3|ca"
}

if (-not (Test-Path $TempPboDir)) { New-Item -ItemType Directory -Path $TempPboDir -Force | Out-Null }

foreach ($pbo in $relevantPbos) {
    if ($neededModels.Count -eq 0) { break }
    
    # Extract
    & $BankRevExe "-f" $TempPboDir $pbo.FullName "*.p3d" 2>$null | Out-Null
    
    # Check extracted files against needed list
    $extractedP3ds = Get-ChildItem -Path $TempPboDir -Recurse -Filter "*.p3d" -ErrorAction SilentlyContinue
    foreach ($file in $extractedP3ds) {
        if ($neededModels.Contains($file.Name)) {
            $targetPath = Join-Path $ExtractedDir $file.Name
            if (-not (Test-Path $targetPath)) {
                Move-Item -Path $file.FullName -Destination $targetPath -Force
                Write-Host "  [+] Extracted: $($file.Name)" -ForegroundColor Green
                $neededModels.Remove($file.Name) | Out-Null
            }
        }
    }
    
    # Clean temp folder
    Remove-Item -Path $TempPboDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $TempPboDir -Force | Out-Null
}

if (Test-Path $TempPboDir) { Remove-Item -Path $TempPboDir -Recurse -Force -ErrorAction SilentlyContinue }

$extractedCount = (Get-ChildItem -Path $ExtractedDir -Filter "*.p3d").Count
if ($extractedCount -eq 0) {
    Write-Host "`nNo new models were extracted. Moving on..." -ForegroundColor Gray
} else {
    Write-Host "`nExtracted $extractedCount new models for debinarization." -ForegroundColor Green
}

# 4. Debinarize (ODOL to MLOD)
if ($extractedCount -gt 0) {
    Write-Host "`n[3/4] Debinarizing models (P3DDebinarizer)..." -ForegroundColor Yellow
    Start-Process -FilePath $DebinarizerExe -ArgumentList """$ExtractedDir"" ""$MlodDir""" -Wait -WindowStyle Hidden
}

# 5. Blender Conversion (MLOD to GLB)
$mlods = Get-ChildItem -Path $MlodDir -Filter "*.p3d"
if ($mlods.Count -gt 0) {
    Write-Host "`n[4/4] Converting MLOD to GLB (Blender - File by File to prevent crashes)..." -ForegroundColor Yellow
    
    $success = 0
    $failed = 0
    $counter = 0
    
    foreach ($mlod in $mlods) {
        $counter++
        $outFile = Join-Path $OutputDir ($mlod.BaseName + ".glb")
        
        if ((Test-Path $outFile) -and (Get-Item $outFile).Length -gt 2KB) {
            Write-Host "[$counter/$($mlods.Count)] Skipping $($mlod.Name) - already successfully converted." -ForegroundColor Gray
            continue
        }
        
        Write-Host "[$counter/$($mlods.Count)] Converting $($mlod.Name)..." -NoNewline
        
        # Run blender headlessly for this specific file
        # We redirect stderr to null to suppress blender spam, but capture exit code
        $process = Start-Process -FilePath $BlenderExe -ArgumentList "--background", "--python", "blender_convert.py", "--", "-i", "`"$($mlod.FullName)`"", "-o", "`"$OutputDir`"" -Wait -NoNewWindow -PassThru
        
        if ($process.ExitCode -eq 0 -and (Test-Path $outFile)) {
            Write-Host " SUCCESS" -ForegroundColor Green
            $success++
        } else {
            Write-Host " CRASH/FAIL" -ForegroundColor Red
            $failed++
            # Delete the partially created GLB if it failed but somehow created a 0-byte file
            if (Test-Path $outFile) { Remove-Item -Path $outFile -Force }
        }
    }
    
    Write-Host "`nConversion Summary: $success Succeeded, $failed Failed." -ForegroundColor Cyan
    
    # Cleanup intermediate files
    Write-Host "`nCleaning up intermediate files..." -ForegroundColor Gray
    Remove-Item -Path "$ExtractedDir\*" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "$MlodDir\*" -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "`n[4/4] No MLOD models to convert." -ForegroundColor Gray
}

Write-Host "`n==============================================" -ForegroundColor Cyan
Write-Host "              PIPELINE COMPLETE               " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
