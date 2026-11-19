# ============================================
# StartllamaMonitor.ps1
# Monitor for automatic restart of llama-server
# ============================================

$LogFile = "C:\Users\Andrey\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\StartllamaMonitor.log"
$CheckInterval = 60  # 10 minutes
$StartFile = "C:\Users\Andrey\Desktop\llama-b10358-bin-win-vulkan-x64\Startllama.bat"

Write-Host "StartllamaMonitor started..." -ForegroundColor Green

while ($true) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    Write-Host "[$timestamp] Scanning for llama processes..." -ForegroundColor Yellow
    
    # Get ALL running processes
    $allProcesses = Get-Process -ErrorAction SilentlyContinue
    
    # Filter for processes with 'llama' in name
    $llamaProcesses = $allProcesses | Where-Object { $_.ProcessName -like '*llama*' }
    
    Write-Host "[$timestamp] Found $([int]$llamaProcesses.Count) llama process(es)" -ForegroundColor Gray
    
    if ($llamaProcesses.Count -eq 0) {
        Write-Host "[$timestamp] NO llama process running. Launching..." -ForegroundColor Red
        
        # Read command from Startllama.bat
        $line = Get-Content $StartFile | Select-Object -First 1
        $command = if ($line -match '^\d+\|(.*)$') { $matches[1] } else { $line }
        
        # Launch using cmd /c in background
        Start-Process cmd -ArgumentList "/c", "$StartFile" -WindowStyle Normal
        
        Start-Sleep -Seconds 5
        Write-Host "[$timestamp] Launch command executed." -ForegroundColor Green
    }
    else {
        Write-Host "[$timestamp] OK. $($llamaProcesses[0].ProcessName) is running (PID: $($llamaProcesses[0].Id))" -ForegroundColor Green
    }
    
    # Log
    if ($llamaProcesses.Count -eq 0) {
        Add-Content -Path $LogFile -Value "[$timestamp] Not running, restarting"
    } else {
        Add-Content -Path $LogFile -Value "[$timestamp] Running ($($llamaProcesses[0].ProcessName))"
    }
    
    Start-Sleep -Seconds $CheckInterval
}
