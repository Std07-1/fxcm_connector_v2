#requires -version 5.1
param(
  [string]$NS = "fxcm_local",
  [string]$RedisHost = "127.0.0.1",
  [int]$RedisPort = 6379,
  [string]$OutDir = "data/audit_v3",
  [string]$ReqId = "eg-p7a-0001",
  [int]$TimeoutSec = 30
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

$prefix = "p7a_${NS}_${ReqId}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$pythonExe = "C:/Aione_projects/fxcm_connector_v2/.venv/Scripts/python.exe"

$env:PYTHONPATH = $Root

$appOut = Join-Path $OutDirPath "$prefix.app_out.txt"
$appErr = Join-Path $OutDirPath "$prefix.app_err.txt"
$uiOut = Join-Path $OutDirPath "$prefix.ui_out.txt"
$uiErr = Join-Path $OutDirPath "$prefix.ui_err.txt"

$appProc = $null
$uiProc = $null

function Stop-SafeProcess {
  param([System.Diagnostics.Process]$Proc)
  if ($null -eq $Proc) {
    return
  }
  try {
    $existing = Get-Process -Id $Proc.Id -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
      return
    }
    if (-not $Proc.HasExited) {
      Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
    }
  }
  catch {
    return
  }
}

try {
  $appProc = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "app.main", "--fxcm-preview") -RedirectStandardOutput $appOut -RedirectStandardError $appErr -PassThru
  Start-Sleep -Seconds 2
  $uiProc = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "ui_lite.server") -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr -PassThru
  Start-Sleep -Seconds 2

  $pyLog = Join-Path $OutDirPath "$prefix.python_out.txt"
  $cmd = @(
    "tools/audit/ws_smoke_ui_lite.py",
    "--ns", $NS,
    "--redis-host", $RedisHost,
    "--redis-port", $RedisPort,
    "--out-dir", $OutDirPath,
    "--prefix", $prefix,
    "--mode", "preview"
  )

  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $pyOut = & $pythonExe @cmd 2>&1
  $pyExit = $LASTEXITCODE
  $ErrorActionPreference = $prevPref
  $pyOut | Set-Content -Encoding UTF8 $pyLog
  if ($pyExit -ne 0) {
    Write-Error "Exit Gate P7A FAIL: ws_smoke exit code $pyExit"
    Write-Host "python_out: $(Resolve-Path $pyLog)"
    exit 2
  }

  $hashLines = Get-ChildItem $OutDirPath -Filter "$prefix*" | ForEach-Object {
    $h = Get-FileHash $_.FullName -Algorithm SHA256
    "$($h.Hash)  $($h.Path)"
  }
  $hashPath = Join-Path $OutDirPath "$prefix.hashes.txt"
  $hashLines | Set-Content -Encoding UTF8 $hashPath

  Write-Host "OK: Exit Gate P7A"
  Write-Host "hashes: $(Resolve-Path $hashPath)"
}
finally {
  Stop-SafeProcess -Proc $appProc
  Stop-SafeProcess -Proc $uiProc
}
