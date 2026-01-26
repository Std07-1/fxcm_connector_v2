#requires -version 5.1
param(
  [string]$NS = "fxcm_local",
  [string]$RedisHost = "127.0.0.1",
  [int]$RedisPort = 6379,
  [string]$OutDir = "data/audit_v3",
  [string]$ReqId = "eg-p7-0001",
  [string]$Mode = "offline"
)

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
Set-Location $Root

$OutDirPath = $OutDir
if (-not [System.IO.Path]::IsPathRooted($OutDirPath)) {
  $OutDirPath = Join-Path $Root $OutDirPath
}
if (-not (Test-Path $OutDirPath)) {
  New-Item -ItemType Directory -Force $OutDirPath | Out-Null
}

$existing = Get-ChildItem $OutDirPath -Filter "*$ReqId*" -ErrorAction SilentlyContinue
if ($null -ne $existing -and $existing.Count -gt 0) {
  Write-Error "OutDir already contains artifacts for ReqId=$ReqId"
  exit 2
}

$ErrorActionPreference = "Stop"

$prefix = "p7_${NS}_${ReqId}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$pythonExe = "C:/Aione_projects/fxcm_connector_v2/.venv/Scripts/python.exe"

$env:PYTHONPATH = $Root

if ($Mode -eq "offline") {
  $py = @"
from pathlib import Path
from config.config import load_config

cfg = load_config()
if cfg.fxcm_backend != "disabled":
    raise SystemExit("fxcm_backend має бути disabled для offline")

out_path = Path(r"$OutDirPath") / "$prefix.offline_check.json"
out_path.write_text(
    "{\"fxcm_backend\": \"%s\", \"profile\": \"%s\"}\n" % (cfg.fxcm_backend, cfg.profile),
    encoding="utf-8",
)
print("OK: offline check")
"@
  $pyLog = Join-Path $OutDirPath "$prefix.python_out.txt"
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $pyOut = & $pythonExe -c $py 2>&1
  $pyExit = $LASTEXITCODE
  $ErrorActionPreference = $prevPref
  $pyOut | Set-Content -Encoding UTF8 $pyLog
  if ($pyExit -ne 0) {
    Write-Error "Exit Gate P7 offline FAIL: python exit code $pyExit"
    Write-Host "python_out: $(Resolve-Path $pyLog)"
    exit 2
  }
}
elseif ($Mode -eq "online") {
  $statusBefore = Join-Path $OutDirPath "$prefix.status_before.json"
  & redis-cli -h $RedisHost -p $RedisPort GET "$NS`:status:snapshot" | Set-Content -Encoding UTF8 $statusBefore

  $capturePath = Join-Path $OutDirPath "$prefix.ohlcv.json"
  $cmd = @(
    "tools/audit/capture_redis_ohlcv_once.py",
    "--ns", $NS,
    "--redis-host", $RedisHost,
    "--redis-port", $RedisPort,
    "--out-path", $capturePath,
    "--mode", "online"
  )

  $pyLog = Join-Path $OutDirPath "$prefix.python_out.txt"
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $pyOut = & $pythonExe @cmd 2>&1
  $pyExit = $LASTEXITCODE
  $ErrorActionPreference = $prevPref
  $pyOut | Set-Content -Encoding UTF8 $pyLog
  if ($pyExit -ne 0) {
    Write-Error "Exit Gate P7 online FAIL: python exit code $pyExit"
    Write-Host "python_out: $(Resolve-Path $pyLog)"
    exit 2
  }

  $statusAfter = Join-Path $OutDirPath "$prefix.status_after.json"
  & redis-cli -h $RedisHost -p $RedisPort GET "$NS`:status:snapshot" | Set-Content -Encoding UTF8 $statusAfter
}
else {
  Write-Error "Невідомий Mode=$Mode (offline|online)"
  exit 2
}

$hashLines = Get-ChildItem $OutDirPath -Filter "$prefix*" | ForEach-Object {
  $h = Get-FileHash $_.FullName -Algorithm SHA256
  "$($h.Hash)  $($h.Path)"
}
$hashPath = Join-Path $OutDirPath "$prefix.hashes.txt"
$hashLines | Set-Content -Encoding UTF8 $hashPath

Write-Host "OK: Exit Gate P7 ($Mode)"
Write-Host "hashes: $(Resolve-Path $hashPath)"
