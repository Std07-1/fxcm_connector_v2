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

$ts = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$payload = @{
  cmd = "fxcm_warmup";
  req_id = "eg-p41-0001";
  ts = $ts;
  args = @{
    symbols = @("XAUUSD");
    lookback_hours = 48;
    publish = $false;
    rebuild_derived = $false;
  }
} | ConvertTo-Json -Compress

$publishPath = Join-Path $OutDir "publish_warmup_p41_cmd.txt"
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

$afterPath = Join-Path $OutDir "status_after_p41.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath

$afterRaw = Get-Content -Raw -Path $afterPath
try {
  $after = $afterRaw | ConvertFrom-Json
} catch {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0LjEgRkFJTDogc3RhdHVzX2FmdGVyX3A0MS5qc29uINC90Lkg0LHRg9C70L4gSlNPTg==')
  exit 1
}

$final = $after.ohlcv_final
if ($null -eq $final) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0LjEgRkFJTDogb2hsY3ZfZmluYWwgbm90IGZvdW5k')
  exit 1
}

$entry = $final."1m"
if ($null -eq $entry) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0LjEgRkFJTDogb2hsY3ZfZmluYWxbIjFtIl0gbWlzc2luZw==')
  exit 1
}

$lastClose = [long]$entry.last_complete_bar_ms
if ($lastClose -le 0) {
  Write-Error (_b64 'RXhpdCBHYXRlIFA0LjEgRkFJTDogb2hsY3ZfZmluYWxbIjFtIl0ubGFzdF9jb21wbGV0ZV9iYXJfbXMgPD0gMA==')
  exit 1
}

$final1m = $after.ohlcv_final_1m
if ($null -ne $final1m) {
  $lastClose1m = [long]$final1m.last_complete_bar_ms
  if ($lastClose1m -le 0) {
    Write-Error (_b64 'RXhpdCBHYXRlIFA0LjEgRkFJTDogb2hsY3ZfZmluYWxfMW0ubGFzdF9jb21wbGV0ZV9iYXJfbXMgPD0gMA==')
    exit 1
  }
}

Write-Host (_b64 'T0s6IEV4aXQgR2F0ZSBQNC4x')
