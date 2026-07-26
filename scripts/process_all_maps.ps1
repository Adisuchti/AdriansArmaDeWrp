$ConfigPath = Join-Path $PSScriptRoot "..\config.json"
if (Test-Path $ConfigPath) {
    $config = Get-Content $ConfigPath | ConvertFrom-Json
    $docPath = $config.exports_dir
} else {
    $docPath = [System.IO.Path]::Combine([Environment]::GetFolderPath("MyDocuments"), "Arma3MapExports")
}

$mapDirs = Get-ChildItem -Path $docPath -Directory

Write-Host "Found $($mapDirs.Count) map directories in $docPath"

foreach ($dir in $mapDirs) {
    # Check if objects.json exists
    $jsonPath = Join-Path $dir.FullName "objects.json"
    if (Test-Path $jsonPath) {
        Write-Host "==============================================" -ForegroundColor Green
        Write-Host " Processing Map Directory: $($dir.Name)" -ForegroundColor Green
        Write-Host "==============================================" -ForegroundColor Green
        
        # Call process_map.ps1 with the directory name
        .\process_map.ps1 -MapName $dir.Name
    } else {
        Write-Host "Skipping $($dir.Name) - no objects.json found." -ForegroundColor Yellow
    }
}

Write-Host "`nAll maps processed successfully!" -ForegroundColor Cyan
