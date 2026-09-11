$dist = 'F:\A_Works\ai-dev-system\dist\AI-Dev-System'
Get-Process AI-Dev-System -ea 0 | Stop-Process -Force
Copy-Item F:\A_Works\ai-dev-system\.env "$dist\.env" -Force -ea 0
Remove-Item "$dist\desktop*.log" -Force -ea 0
Start-Process "$dist\AI-Dev-System.exe" -ArgumentList '--backend' -WorkingDirectory $dist
$ok = $false
for ($i = 1; $i -le 45; $i++) {
    Start-Sleep 1
    try {
        $c = (Invoke-WebRequest http://127.0.0.1:18000/api/health -UseBasicParsing -TimeoutSec 1).Content
        Write-Output "HEALTH OK ${i}s $c"
        $ok = $true
        break
    } catch {
        if ($i % 5 -eq 0) { Write-Output "wait $i" }
    }
}
if (-not $ok) { Write-Output 'FAILED' }
Write-Output '---log---'
Get-Content "$dist\desktop.log" -ea 0 -Encoding UTF8
Write-Output '---err---'
Get-Content "$dist\desktop-backend-error.log" -ea 0 -Encoding UTF8
Write-Output '---stdout---'
Get-Content "$dist\desktop-backend-stdout.log" -ea 0 -Encoding UTF8 | Select-Object -Last 50
netstat -ano | findstr :18000
Get-Process AI-Dev-System -ea 0 | Format-Table Id, CPU
Get-Process AI-Dev-System -ea 0 | Stop-Process -Force
Write-Output 'done'
