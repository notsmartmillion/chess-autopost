# Daily chess autopost runner (Windows).
#
# Register with Task Scheduler (run once):
#   schtasks /Create /TN "ChessAutopost" /SC DAILY /ST 07:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\ai\projects\chess-autopost\services\orchestrator\run_daily.ps1"
# Remove it again with:
#   schtasks /Delete /TN "ChessAutopost" /F
#
# Keep this file ASCII-only: Windows PowerShell 5.1 reads .ps1 as ANSI unless
# the file has a BOM, and a stray UTF-8 character decodes into a smart quote
# that breaks parsing.

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv missing. Create it first:"
    Write-Host "  py -3.11 -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -e ./apps/analyzer[dev] pyttsx3 pydub requests python-dateutil"
    exit 1
}

$logDir = Join-Path $root "outputs\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("daily_" + (Get-Date -Format "yyyy-MM-dd_HHmmss") + ".log")

Write-Host "Chess autopost starting. Log: $log"

# Any arguments given to this script are forwarded to flow.py.
& $py (Join-Path $root "services\orchestrator\flow.py") @args *>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE

if ($code -ne 0) {
    Write-Host "Daily run FAILED with exit code $code. See $log"
} else {
    Write-Host "Daily run finished."
}

# Keep the last 30 logs only.
Get-ChildItem $logDir -Filter "daily_*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $code
