$root = Split-Path -Parent $PSScriptRoot
$port = 8755
Get-Content "$root\.env" | ForEach-Object { if ($_ -match '^\s*SERVER_PORT\s*=\s*(\d+)') { $port = [int]$matches[1] } }
New-Item -ItemType Directory -Force "$root\logs" | Out-Null
"==== $(Get-Date) start ====" | Add-Content "$root\logs\stdout.log"
$p = Start-Process "$root\.venv\Scripts\pythonw.exe" -ArgumentList '-m', 'laya_trader' -WorkingDirectory $root -PassThru
Write-Host "server pid $($p.Id) starting" -NoNewline
for ($i = 0; $i -lt 90; $i++) {
  if ($p.HasExited) {
    Write-Host "`nserver exited (code $($p.ExitCode)). last log:"
    Get-Content "$root\logs\stdout.log" -Tail 25
    exit 1
  }
  try {
    Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 1 | Out-Null
    Write-Host "`nready: http://127.0.0.1:$port"
    Start-Process "http://127.0.0.1:$port"
    exit 0
  } catch { Write-Host "." -NoNewline; Start-Sleep 1 }
}
Write-Host "`ntimeout - check logs\server.log"
exit 1
