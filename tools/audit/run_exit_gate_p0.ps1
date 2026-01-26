#requires -version 5.1
param(
  [string]$NS = "fxcm_local",
  [string]$RedisHost = "127.0.0.1",
  [int]$RedisPort = 6379
)

$ErrorActionPreference = "Stop"

# UTF-8 без BOM для консолі та пайпу в redis-cli
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

$ts = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

# Snapshot ДО
$beforePath = Join-Path $OutDir "status_snapshot_before.json"
$StatusKey = "$($NS):status:snapshot"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $beforePath

# Publish unknown command
$payload = @{ cmd = "unknown_cmd"; req_id = "eg-p0-0001"; ts = $ts; args = @{} } | ConvertTo-Json -Compress
$publishPath = Join-Path $OutDir "publish_unknown_cmd.txt"
$CommandsChannel = "$($NS):commands"
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
$publishOutput = ($stdout + $stderr).Trim()
$publishOutput | Set-Content -Encoding UTF8 $publishPath

# Snapshot ПІСЛЯ
$afterPath = Join-Path $OutDir "status_snapshot_after.json"
& redis-cli -h $RedisHost -p $RedisPort GET $StatusKey | Set-Content -Encoding UTF8 $afterPath

# Metrics (якщо доступно)
$metricsPath = Join-Path $OutDir "metrics.txt"
try {
  Invoke-WebRequest "http://127.0.0.1:9200/metrics" -UseBasicParsing | Select-Object -ExpandProperty Content | Set-Content -Encoding UTF8 $metricsPath
} catch {
  # Не фейлити: metrics можуть бути недоступні
}

# Fail-fast перевірки
$afterText = Get-Content -Raw -Path $afterPath
if ($afterText -notmatch "unknown_command") {
  Write-Error "Exit Gate P0 FAIL: unknown_command не знайдено у status_snapshot_after.json"
  exit 1
}
if ($afterText -notmatch '"state"\s*:\s*"error"') {
  Write-Error "Exit Gate P0 FAIL: last_command.state != error у status_snapshot_after.json"
  exit 1
}

Write-Host "OK: Exit Gate P0"
