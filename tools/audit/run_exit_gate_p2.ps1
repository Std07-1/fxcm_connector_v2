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

$beforePath = Join-Path $OutDir "status_before_preview.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $beforePath

Start-Sleep -Seconds 5

$afterPath = Join-Path $OutDir "status_after_preview.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath

$beforeRaw = Get-Content -Raw -Path $beforePath
$afterRaw = Get-Content -Raw -Path $afterPath
try {
  $before = $beforeRaw | ConvertFrom-Json
  $after = $afterRaw | ConvertFrom-Json
} catch {
  Write-Error (_b64 'RXhpdCBHYXRlIFAyIEZBSUw6IHN0YXR1c19hZnRlcl9wcmV2aWV3Lmpzb24g0L3QtSDRlCDQstCw0LvRltC00L3QuNC8IEpTT04=')
  exit 1
}

$previewBefore = $before.ohlcv_preview
$previewAfter = $after.ohlcv_preview
if ($null -eq $previewAfter) {
  Write-Error (_b64 'RXhpdCBHYXRlIFAyIEZBSUw6IG9obGN2X3ByZXZpZXcg0LLRltC00YHRg9GC0L3RltC5INGDINGB0YLQsNGC0YPRgdGW')
  exit 1
}

$beforeTotal = [long]$previewBefore.preview_total
$afterTotal = [long]$previewAfter.preview_total
if ($afterTotal -le $beforeTotal) {
  Write-Error (_b64 'RXhpdCBHYXRlIFAyIEZBSUw6IHByZXZpZXdfdG90YWwg0L3QtSDQt9Cx0ZbQu9GM0YjQuNCy0YHRjw==')
  exit 1
}

$tfList = @("1m","5m","15m","1h","4h","1d")
foreach ($tf in $tfList) {
  $value = [long]$previewAfter.last_bar_open_time_ms.$tf
  if ($value -le 0) {
    $prefix = _b64 'RXhpdCBHYXRlIFAyIEZBSUw6IGxhc3RfYmFyX29wZW5fdGltZV9tcyDQtNC70Y8gdGY9'
    Write-Error ($prefix + $tf + ' <= 0')
    exit 1
  }
}

Write-Host (_b64 'T0s6IEV4aXQgR2F0ZSBQMg==')
