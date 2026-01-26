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

$beforePath = Join-Path $OutDir "status_before_tick.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $beforePath

Start-Sleep -Seconds 3

$afterPath = Join-Path $OutDir "status_after_tick.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath

$afterRaw = Get-Content -Raw -Path $afterPath
try {
  $after = $afterRaw | ConvertFrom-Json
} catch {
  Write-Error (_b64 'RXhpdCBHYXRlIFAxIEZBSUw6IHN0YXR1c19hZnRlcl90aWNrLmpzb24g0L3QtSDRlCDQstCw0LvRltC00L3QuNC8IEpTT04=')
  exit 1
}

$price = $after.price
if ($null -eq $price) {
  Write-Error (_b64 'RXhpdCBHYXRlIFAxIEZBSUw6IHByaWNlINGB0LXQutGG0ZbRjyDQstGW0LTRgdGD0YLQvdGPINGDINGB0YLQsNGC0YPRgdGW')
  exit 1
}
if ([long]$price.tick_total -le 0) {
  Write-Error (_b64 'RXhpdCBHYXRlIFAxIEZBSUw6IHByaWNlLnRpY2tfdG90YWwgPD0gMA==')
  exit 1
}
if ([long]$price.last_tick_ts_ms -le 0) {
  Write-Error (_b64 'RXhpdCBHYXRlIFAxIEZBSUw6IHByaWNlLmxhc3RfdGlja190c19tcyA8PSAw')
  exit 1
}

Write-Host (_b64 'T0s6IEV4aXQgR2F0ZSBQMQ==')
