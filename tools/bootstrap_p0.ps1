#requires -version 5.1
$ErrorActionPreference = 'Stop'

function _b64([string]$value) {
  return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($value))
}

[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root

$Py = $env:PY_BIN
if ([string]::IsNullOrWhiteSpace($Py)) {
  $Py = 'py -3.7'
}

$PyExe = $Py
$PyArgs = @()
if ($Py -match '\s') {
  $parts = $Py -split '\s+'
  $PyExe = $parts[0]
  if ($parts.Length -gt 1) {
    $PyArgs = $parts[1..($parts.Length - 1)]
  }
}

try {
  & $PyExe @PyArgs -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,7) else 2)' | Out-Null
} catch {
  Write-Error (_b64 'UHl0aG9uIDMuNyDQvdC1INC30L3QsNC50LTQtdC90L4uINCS0YHRgtCw0L3QvtCy0LggUHl0aG9uIDMuNyDQsNCx0L4g0LfQsNC00LDQuSBQWV9CSU4gKNC90LDQv9GA0LjQutC70LDQtDogQzpcUHl0aG9uMzdccHl0aG9uLmV4ZSku')
  exit 2
}

if (-not (Test-Path '.venv')) {
  & $PyExe @PyArgs -m venv .venv
}

$Activate = Join-Path $Root '.venv\Scripts\Activate.ps1'
. $Activate

python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -r requirements-dev.txt

ruff check .
mypy .
pytest -q
python -m tools.run_exit_gates --out reports\exit_gates --manifest tools\exit_gates\manifest_p0.json

Write-Host (_b64 '0JTQsNC70ZY6INC30LDQv9GD0YHRgtC4IGFwcC5tYWluINGWINCy0LjQutC+0L3QsNC5INC30LDQtNCw0YfRgyBWUyBDb2RlIEF1ZGl0OiBFeGl0IEdhdGUgUDAg0LTQu9GPIHByb29mLXBhY2s=')
Write-Host (_b64 '0JTQu9GPIFAxOiDQstC40LrQvtC90LDQuSB0b29scy9hdWRpdC9ydW5fZXhpdF9nYXRlX3AxLnBzMSDRidC+0LEg0L/RltC00YLQstC10YDQtNC40YLQuCB0aWNrIGZlZWQ=')
Write-Host (_b64 '0JTQu9GPIFAyOiDQstC40LrQvtC90LDQuSB0b29scy9hdWRpdC9ydW5fZXhpdF9nYXRlX3AyLnBzMSDRidC+0LEg0L/RltC00YLQstC10YDQtNC40YLQuCBwcmV2aWV3')
Write-Host (_b64 'T0s6IFAwIGJvb3RzdHJhcCDQt9Cw0LLQtdGA0YjQtdC90L4=')
