#requires -version 5.1
param(
  [string]$NS = "fxcm_local",
  [string]$RedisHost = "127.0.0.1",
  [int]$RedisPort = 6379
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

$OutDir = Join-Path $Root "data\audit_v3"
if (-not (Test-Path $OutDir)) {
  New-Item -ItemType Directory -Force $OutDir | Out-Null
}

$StatusKey = "$($NS):status:snapshot"
$CommandsChannel = "$($NS):commands"

$beforePath = Join-Path $OutDir "status_before_p4.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $beforePath

$ts = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$payload = @{
  cmd = "fxcm_rebuild_derived";
  req_id = "eg-p4-0001";
  ts = $ts;
  args = @{
    symbol = "XAUUSD";
    window_hours = 48;
    tfs = @("15m", "1h", "4h", "1d");
  }
} | ConvertTo-Json -Compress

$publishPath = Join-Path $OutDir "publish_rebuild_cmd.txt"
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

Start-Sleep -Seconds 5

$afterPath = Join-Path $OutDir "status_after_p4.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath

$beforeRaw = Get-Content -Raw -Path $beforePath
$afterRaw = Get-Content -Raw -Path $afterPath
try {
  $before = $beforeRaw | ConvertFrom-Json
} catch {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0IEZBSUw6IHN0YXR1c19iZWZvcmVfcDQuanNvbiDQvdC1INGUINCy0LDQu9GW0LTQvdC40LwgSlNPTg==')
  exit 1
}
try {
  $after = $afterRaw | ConvertFrom-Json
} catch {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0IEZBSUw6IHN0YXR1c19hZnRlcl9wNC5qc29uINC90Lkg0LHRg9C70L4gSlNPTg==')
  exit 1
}

$derived = $after.derived_rebuild
if ($null -eq $derived -or $derived.state -ne "ok") {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0IEZBSUw6IGRlcml2ZWRfcmVidWlsZC5zdGF0ZSAhPSAib2si')
  exit 1
}

$final = $after.ohlcv_final
if ($null -eq $final) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0IEZBSUw6IG9obGN2X2ZpbmFsINC90Lkg0LHRg9C70L4gSlNPTg==')
  exit 1
}

$checks = @("15m", "1h", "4h", "1d")
foreach ($tf in $checks) {
  $entry = $final.$tf
  if ($null -eq $entry) {
    Write-Error ("Exit Gate P4 FAIL: ohlcv_final.$tf missing")
    exit 1
  }
  $lastClose = [long]$entry.last_complete_bar_ms
  if ($lastClose -le 0) {
    Write-Error ("Exit Gate P4 FAIL: ohlcv_final.$tf.last_complete_bar_ms <= 0")
    exit 1
  }
}

Write-Host (_b64 'T0s6IEV4aXQgR2F0ZSBQNA==')
