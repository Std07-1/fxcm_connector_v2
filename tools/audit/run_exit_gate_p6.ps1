#requires -version 5.1
param(
  [string]$NS = "fxcm_local",
  [string]$RedisHost = "127.0.0.1",
  [int]$RedisPort = 6379,
  [string]$OutDir = "data/audit_v3",
  [string]$ReqId = "eg-p6-0001"
)

$ErrorActionPreference = "Stop"

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

$prefix = "p6_${NS}_${ReqId}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$StatusKey = "$($NS):status:snapshot"

$beforePath = Join-Path $OutDirPath "$prefix.status_before.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $beforePath

$pythonExe = "C:/Aione_projects/fxcm_connector_v2/.venv/Scripts/python.exe"
$py = @"
from pathlib import Path
from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.no_mix import NoMixDetector
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
import redis

root_dir = Path.cwd()
validator = SchemaValidator(root_dir=root_dir)
config = Config(ns="$NS", commands_enabled=False)
calendar = Calendar([], config.calendar_tag)
redis_client = redis.Redis.from_url(config.redis_dsn(), decode_responses=True)
publisher = RedisPublisher(redis_client, config)
status = StatusManager(config=config, validator=validator, publisher=publisher, calendar=calendar, metrics=None)
status.build_initial_snapshot()

detector = NoMixDetector()

payload_a = {
    "symbol": "XAUUSD",
    "tf": "1m",
    "source": "history",
    "bars": [{"open_time": 1000, "complete": True}],
}
payload_b = {
    "symbol": "XAUUSD",
    "tf": "1m",
    "source": "history_alt",
    "bars": [{"open_time": 1000, "complete": True}],
}

detector.check_final_payload(payload_a, status)
detector.check_final_payload(payload_b, status)
status.publish_snapshot()
"@

$pyFile = Join-Path $OutDirPath "$prefix.no_mix_sim.py"
$py | Set-Content -Encoding UTF8 $pyFile
$pyLog = Join-Path $OutDirPath "$prefix.python_out.txt"
$env:PYTHONPATH = $Root
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pyOut = & $pythonExe $pyFile 2>&1
$pyExit = $LASTEXITCODE
$ErrorActionPreference = $prevPref
$pyOut | Set-Content -Encoding UTF8 $pyLog
if ($pyExit -ne 0) {
  Write-Error "Exit Gate P6 FAIL: python exit code $pyExit"
  Write-Host "python_out: $(Resolve-Path $pyLog)"
  exit 2
}

$afterPath = Join-Path $OutDirPath "$prefix.status_after.json"
$after = $null
for ($i = 0; $i -lt 5; $i++) {
  & redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath
  $afterRaw = Get-Content -Raw -Path $afterPath
  try {
    $after = $afterRaw | ConvertFrom-Json
  } catch {
    $after = $null
  }
  if ($null -ne $after) { break }
  Start-Sleep -Milliseconds 200
}
if ($null -eq $after) {
  Write-Error "Exit Gate P6 FAIL: status_after JSON parse"
  exit 1
}

if ($after.no_mix.conflicts_total -lt 1) {
  Write-Error "Exit Gate P6 FAIL: conflicts_total < 1"
  exit 1
}

$codes = $after.errors.code
if ($null -eq $codes -or -not ($codes -contains "no_mix_final_source_conflict")) {
  Write-Error "Exit Gate P6 FAIL: no_mix_final_source_conflict missing"
  exit 1
}

Write-Host "OK: Exit Gate P6"
Write-Host "before: $(Resolve-Path $beforePath)"
Write-Host "after: $(Resolve-Path $afterPath)"
