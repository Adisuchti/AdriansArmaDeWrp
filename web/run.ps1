# Start local Python HTTP Server
Write-Host "Starting Arma 3 Web Viewer Server..." -ForegroundColor Cyan

# Start Python server in the background
$process = Start-Process -FilePath "python" -ArgumentList "server.py" -PassThru -NoNewWindow

Write-Host "Server running on http://localhost:8000" -ForegroundColor Green
Write-Host "Opening browser in 2 seconds..."

Start-Sleep -Seconds 2
Start-Process "http://localhost:8000"

Write-Host "Press any key to stop the server and exit..."
$Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") | Out-Null

Stop-Process -Id $process.Id -Force
Write-Host "Server stopped." -ForegroundColor Cyan
