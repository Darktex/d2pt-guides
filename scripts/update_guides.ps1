# Refresh and reinstall all D2PT guides. Meant to run unattended from a
# Windows scheduled task, e.g.:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_guides.ps1 `
#       -GuidesDir "C:\...\Steam\userdata\<account>\570\remote\guides"
#
# Exits 1 without touching anything if Dota 2 is running (the client only
# picks up guide files at startup) so Task Scheduler's restart-on-failure
# can retry later. Appends a log to output\update.log in the repo.
param(
    [string]$GuidesDir = ""
)

$repo = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repo "output"
$log = Join-Path $outDir "update.log"
New-Item -ItemType Directory -Force $outDir | Out-Null

function Write-Log($msg) { "$(Get-Date -Format s) $msg" | Add-Content $log }

if (Get-Process -Name dota2 -ErrorAction SilentlyContinue) {
    Write-Log "Dota 2 is running; skipping this attempt."
    exit 1
}

Set-Location $repo
$cmd = "python -m d2pt_guides --all-heroes --install --replace"
if ($GuidesDir) { $cmd += " --guides-dir ""$GuidesDir""" }
Write-Log "Running: $cmd"
# cmd handles the redirection so PowerShell 5.1 doesn't wrap stderr lines
# in ErrorRecords.
cmd /c "$cmd >> ""$log"" 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Log "FAILED (exit $LASTEXITCODE)"
    exit 1
}
Write-Log "Done."
exit 0
