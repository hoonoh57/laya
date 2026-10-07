$root = Split-Path -Parent $PSScriptRoot
$port = 8800
Get-Content "$root\.env" | ForEach-Object { if ($_ -match '^\s*SERVER_PORT\s*=\s*(\d+)') { $port = [int]$matches[1] } }
for ($i = 0; $i -lt 60; $i++) {
  try {
    Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 2 | Out-Null
    Start-Process "http://127.0.0.1:$port"
    exit 0
  } catch { Start-Sleep 1 }
}
exit 1
