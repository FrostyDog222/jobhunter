# Restart only the web app, never the sign-in / prefill browser subprocesses.
# A blanket "taskkill /IM python.exe" kills those too, which closes a sign-in window
# out from under whoever is typing into it.
$ErrorActionPreference = 'SilentlyContinue'
$owners = (Get-NetTCPConnection -LocalPort 8777 -State Listen).OwningProcess | Select-Object -Unique
foreach ($procId in $owners) { Stop-Process -Id $procId -Force }
Start-Sleep -Milliseconds 800
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "app.py" `
  -RedirectStandardOutput "srv.log" -RedirectStandardError "srv.err.log" -WindowStyle Hidden
Start-Sleep -Seconds 5
try { (Invoke-WebRequest "http://127.0.0.1:8777/" -UseBasicParsing).StatusCode } catch { "not up" }
