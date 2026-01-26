#requires -version 5.1
param(
  [string]$NS = "fxcm_local",
  [string]$RedisHost = "127.0.0.1",
  [int]$RedisPort = 6379,
  [string]$OutDir = "data/audit_v3",
  [string]$ReqId = "eg-p5-0001"
)

$ErrorActionPreference = "Stop"

function _b64([string]$value) {
  return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($value))
}

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

$prefix = "p5_${NS}_${ReqId}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

$StatusKey = "$($NS):status:snapshot"
$CommandsChannel = "$($NS):commands"

$beforePath = Join-Path $OutDirPath "$prefix.status_before.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $beforePath

$beforeRaw = Get-Content -Raw -Path $beforePath
try {
  $before = $beforeRaw | ConvertFrom-Json
} catch {
  $before = $null
}
if ($null -eq $before) {
  Write-Error "Exit Gate P5 FAIL: status_before JSON parse"
  exit 2
}
if ($before.command_bus.state -ne "running") {
  Write-Error "Exit Gate P5 FAIL: command_bus.state != running"
  exit 2
}

$numsubPath = Join-Path $OutDirPath "$prefix.redis_numsub.txt"
$numsubRaw = & redis-cli -h $RedisHost -p $RedisPort PUBSUB NUMSUB $CommandsChannel
$numsubText = ($numsubRaw | Out-String).Trim()
$numsubText | Set-Content -Encoding UTF8 $numsubPath
$parts = $numsubText -split "\s+"
if ($parts.Length -lt 2) {
  Write-Error "Exit Gate P5 FAIL: NUMSUB parse"
  exit 2
}
$numsubCount = [int]$parts[1]
if ($numsubCount -lt 1) {
  Write-Error "Exit Gate P5 FAIL: NUMSUB < 1"
  exit 2
}

$ts = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$payload = @{
  cmd = "fxcm_tail_guard";
  req_id = $ReqId;
  ts = $ts;
  args = @{
    symbols = @("XAUUSD");
    window_hours = 48;
    repair = $true;
    republish_after_repair = $true;
    republish_force = $true;
    tfs = @("1m");
  }
} | ConvertTo-Json -Compress

$publishPath = Join-Path $OutDirPath "$prefix.publish_cmd.txt"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "redis-cli"
$psi.Arguments = "-h $RedisHost -p $RedisPort -x PUBLISH $CommandsChannel"
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
$null = $proc.Start()
$stdin = New-Object System.IO.StreamWriter($proc.StandardInput.BaseStream, $Utf8NoBom)
$stdin.Write($payload)
$stdin.Flush()
$stdin.Close()
$stdout = $proc.StandardOutput.ReadToEnd()
$stderr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()
($stdout + $stderr).Trim() | Set-Content -Encoding UTF8 $publishPath

$afterPath = Join-Path $OutDirPath "$prefix.status_after.json"
$after = $null
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Milliseconds 500
  & redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath
  $afterRaw = Get-Content -Raw -Path $afterPath
  try {
    $after = $afterRaw | ConvertFrom-Json
  } catch {
    $after = $null
  }
  if ($null -ne $after -and $after.last_command.req_id -eq $ReqId -and $after.last_command.state -ne "running") {
    break
  }
}
if ($null -eq $after) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHN0YXR1c19hZnRlcl9wNS5qc29uINC90Lkg0LHRg9C70L4gSlNPTg==')
  exit 1
}

$cmd = $after.last_command
if ($null -eq $cmd) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IGxhc3RfY29tbWFuZCBtaXNzaW5n')
  exit 1
}
if ($cmd.req_id -ne $ReqId) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IGxhc3RfY29tbWFuZC5yZXFfaWQgbWlzbWF0Y2g=')
  exit 1
}
if ($cmd.cmd -ne "fxcm_tail_guard") {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IGxhc3RfY29tbWFuZC5jbWQgbWlzbWF0Y2g=')
  exit 1
}
if ($cmd.state -ne "ok" -and $cmd.state -ne "error") {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IGxhc3RfY29tbWFuZC5zdGF0ZSBub3Qgb2svZXJyb3I=')
  exit 1
}

$tail = $after.tail_guard
if ($null -eq $tail) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHRhaWxfZ3VhcmQgZW1wdHk=')
  exit 1
}

$lastAudit = [long]$tail.last_audit_ts_ms
if ($lastAudit -le 0) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHRhaWxfZ3VhcmQubGFzdF9hdWRpdF90c19tcyA8PSAw')
  exit 1
}

$state1m = $tail.tf_states."1m".state
if ($state1m -eq "idle") {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHRhaWxfZ3VhcmQudGZfc3RhdGVzWyIx bSJdLnN0YXRlIGlkbGU=')
  exit 1
}
if ($state1m -ne "ok" -and $state1m -ne "deferred" -and $state1m -ne "error") {
  Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHRhaWxfZ3VhcmQudGZfc3RhdGVzWyIx bSJdLnN0YXRlIG5vdCBvay9kZWZlcnJlZA==')
  exit 1
}

if ($state1m -eq "deferred") {
  $degraded = $after.degraded
  if ($null -eq $degraded -or ($degraded -notcontains "repair_deferred_market_open")) {
    Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IGRlZmVycmVkIGJ1dCBkZWdyYWRlZCB0YWcgbWlzc2luZw==')
    exit 1
  }
}

$marketOpen = $after.market.is_open
if ($marketOpen -eq $false) {
  if ($tail.repaired -ne $true -and $cmd.state -ne "error") {
    Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHJlcGFpcmVkIGZhbHNlIHdoZW4gbWFya2V0IGNsb3NlZA==')
    exit 1
  }
}

if ($cmd.state -eq "error") {
  $errors = $after.errors
  if ($null -eq $errors -or -not ($errors.code -contains "ssot_empty")) {
    Write-Error (_b64 'RXhpdCBHYXRlIFA1IEZBSUw6IHNzb3RfZW1wdHkgbWlzc2luZw==')
    exit 1
  }
}

Write-Host (_b64 'T0s6IEV4aXQgR2F0ZSBQNQ==')
Write-Host "before: $(Resolve-Path $beforePath)"
Write-Host "publish: $(Resolve-Path $publishPath)"
Write-Host "after: $(Resolve-Path $afterPath)"
Write-Host "numsub: $(Resolve-Path $numsubPath)"
Get-FileHash -Path $afterPath -Algorithm SHA256 | Format-List
