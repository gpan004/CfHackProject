# Stops the Ingaze backend (:8000) and frontend (:5173), including the orphaned worker process that
# uvicorn --reload leaves behind on Windows when its window is closed (it keeps holding port 8000).
$ports = 8000, 5173
for ($i = 0; $i -lt 3; $i++) {
    $owners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports } |
                Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -eq 0) { break }
    foreach ($procId in $owners) {
        # kill the owner and its children; if the owner is already dead, kill the children still holding its socket
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}
# close the launcher windows
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "Ingaze (BACKEND|FRONTEND)" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$left = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports })
if ($left.Count) { Write-Warning ("Still in use: " + (($left | ForEach-Object { "port $($_.LocalPort) (PID $($_.OwningProcess))" }) -join ", ")) }
else { Write-Host "Ingaze stopped (ports 8000 and 5173 free)." }
