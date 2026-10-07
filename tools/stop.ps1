param([switch]$Quiet)
$root = Split-Path -Parent $PSScriptRoot
$port = 8755; $bport = 8801
if (Test-Path "$root\.env") {
  Get-Content "$root\.env" | ForEach-Object {
    if ($_ -match '^\s*SERVER_PORT\s*=\s*(\d+)') { $port = [int]$matches[1] }
    if ($_ -match '^\s*BRIDGE_PORT\s*=\s*(\d+)') { $bport = [int]$matches[1] }
  }
}
# 1) 정상 종료 요청 (조건 해제, 브리지 정리)
try { Invoke-RestMethod -Method Post "http://127.0.0.1:$port/api/shutdown" -TimeoutSec 3 | Out-Null; Start-Sleep 3 } catch {}

# 2) 남은 프로세스 수집: pid 파일, 포트 점유, 이 프로젝트의 python 프로세스
$ids = @()
foreach ($f in 'server.pid', 'bridge.pid') {
  $p = "$root\run\$f"
  if (Test-Path $p) { $ids += [int](Get-Content $p); Remove-Item $p -Force }
}
foreach ($pt in $port, $bport) {
  $ids += (Get-NetTCPConnection -LocalPort $pt -State Listen -ErrorAction SilentlyContinue).OwningProcess
}
$esc = [regex]::Escape($root)
$ids += (Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'laya_trader|cybos_bridge\.py' -and $_.CommandLine -match $esc }).ProcessId

# 3) python 프로세스만 강제 종료 (다른 프로그램 보호)
$ids | Where-Object { $_ -and $_ -ne $PID } | Sort-Object -Unique | ForEach-Object {
  $pr = Get-Process -Id $_ -ErrorAction SilentlyContinue
  if ($pr -and $pr.ProcessName -like 'python*') {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    if (-not $Quiet) { "killed $_ $($pr.ProcessName)" }
  } elseif ($pr -and -not $Quiet) { "skip $_ $($pr.ProcessName) (not python)" }
}
