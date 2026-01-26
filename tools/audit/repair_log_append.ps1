#requires -version 5.1
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
$LogPath = Join-Path $Root "Work\01log.md"
$ReportPath = Join-Path $Root "data\audit_v3\log_scan_report.json"

function _b64([string]$value) {
  return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($value))
}

if (-not (Test-Path $ReportPath)) {
  throw "log_scan_report.json не знайдено: $ReportPath"
}

$reportRaw = Get-Content -Raw -Path $ReportPath
$report = $reportRaw | ConvertFrom-Json
$entries = @()
if ($report.PSObject.Properties.Name -contains "entries") {
  $entries = $report.entries
}

$timestamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$emDash = [char]0x2014
$arrow = [char]0x2192

$lines = @()
$lines += "## $timestamp $emDash LOG REPAIR $arrow P3 journal normalization (append-only)"
$lines += (_b64 "LSDQn9GA0L7QsdC70LXQvNCwICBDb3BpbG90INGA0L7Qt9C60LjQtNCw0LIgUDMgUFJFL1BPU1Qg0L/QviDRhNCw0LnQu9GDLCDQttGD0YDQvdCw0Lsg0L3QtSDQu9GW0L3RltC50L3QuNC5Lg==")
$lines += (_b64 "LSDQqdC+INC30YDQvtCx0LvQtdC90L4gINC30ZbQsdGA0LDQvdC+INGW0L3QtNC10LrRgdC4INC30LDQv9C40YHRltCyINGDIGRhdGEvYXVkaXRfdjMvbG9nX3NjYW5fcmVwb3J0Lmpzb24g0ZYg0L3QsNCy0LXQtNC10L3QviDQv9C+0YHQuNC70LDQvdC90Y8g0L3QuNC20YfQtS4=")
$lines += (_b64 "LSDQhtC90LTQtdC60YEg0LfQvdCw0LnQtNC10L3QuNGFINC30LDQv9C40YHRltCyIA==")

if ($entries -and $entries.Count -gt 0) {
  foreach ($entry in $entries) {
    $lineNo = $entry.line
    $header = $entry.header
    $lines += "  - [line $lineNo] $header"
  }
} else {
  $lines += (_b64 "ICAtIE1JU1NJTkc6INGW0L3QtNC10LrRgdC4INC90LUg0LfQvdCw0LnQtNC10L3RliDRgyBkYXRhL2F1ZGl0X3YzL2xvZ19zY2FuX3JlcG9ydC5qc29u")
}

$lines += (_b64 "LSBQcm9vZi1wYWNrINCw0YDRgtC10YTQsNC60YLQuCBQMyAo0Y/QutGJ0L4g0ZbRgdC90YPRjtGC0YwpIA==")

$artifactList = @(
  "data/audit_v3/status_before_warmup.json",
  "data/audit_v3/status_after_warmup.json",
  "data/audit_v3/publish_cmd.txt"
)
foreach ($artifact in $artifactList) {
  $fullPath = Join-Path $Root $artifact
  if (Test-Path $fullPath) {
    $lines += "  - $artifact"
  } else {
    $lines += "  - MISSING: $artifact"
  }
}

$lines += (_b64 "LSBSYWlsICDQktGW0LTRgtC10L/QtdGAINCS0KHQhiDQvdC+0LLRliDQt9Cw0L/QuNGB0Lgg0LIgV29yay8wMWxvZy5tZCDQtNC+0LTQsNGO0YLRjNGB0Y8g0KLQhtCb0KzQmtCYINCSINCa0IbQndCV0KbQrC4g0JfQsNCx0L7RgNC+0L3QtdC90L4g0LLRgdGC0LDQstC70Y/RgtC4L9GA0LXQtNCw0LPRg9Cy0LDRgtC4INC/0L7Qv9C10YDQtdC00L3RliDQt9Cw0L/QuNGB0LguINCR0YPQtNGMLdGP0LrQuNC5IHJlcGFpciDRgNC+0LHQuNGC0YzRgdGPINGH0LXRgNC10Lcg0L3QvtCy0LjQuSBhcHBlbmQtb25seSDQsdC70L7Qui4=")
$lines += ""

Add-Content -Path $LogPath -Value $lines -Encoding UTF8
