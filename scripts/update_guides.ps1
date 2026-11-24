# Refresh and reinstall all D2PT guides. Meant to run unattended and with no
# window from a Windows scheduled task, e.g.:
#   conhost.exe --headless powershell -NoProfile -NonInteractive -WindowStyle Hidden `
#       -ExecutionPolicy Bypass -File scripts\update_guides.ps1 `
#       -GuidesDir "C:\...\Steam\userdata\<account>\570\remote\guides"
#
# The task fires weekly and at every logon. This script decides whether
# there is anything to do:
#   - If the last successful update is younger than -MinAgeDays and was made
#     for the current patch, exit 0. A new patch (or -Force) updates at once.
#   - If Dota 2 is running, wait quietly until it closes (the client only
#     picks up guide files at startup), up to -MaxWaitHours.
# Appends a log to output\update.log and records the last successful run in
# output\last_success.txt.
param(
    [string]$GuidesDir = "",
    [double]$MinAgeDays = 6,
    [double]$MaxWaitHours = 16,
    [int]$PollSeconds = 60,
    [switch]$Force
)

$repo = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repo "output"
$log = Join-Path $outDir "update.log"
$stamp = Join-Path $outDir "last_success.txt"
$patchStamp = Join-Path $outDir "last_patch.txt"
New-Item -ItemType Directory -Force $outDir | Out-Null

function Write-Log($msg) {
    # Retry briefly: the log may be momentarily locked by a reader.
    for ($i = 0; $i -lt 5; $i++) {
        try { "$(Get-Date -Format s) $msg" | Add-Content $log -ErrorAction Stop; return }
        catch { Start-Sleep -Milliseconds 200 }
    }
}
function Test-Dota { [bool](Get-Process -Name dota2 -ErrorAction SilentlyContinue) }

Set-Location $repo
$patch = (cmd /c "python -m d2pt_guides --print-patch 2>nul" | Select-Object -First 1)
if ($patch) { $patch = $patch.Trim() }
$lastPatch = if (Test-Path $patchStamp) { (Get-Content $patchStamp -Raw).Trim() } else { "" }
$newPatch = $patch -and ($patch -ne $lastPatch)

if (-not $Force -and -not $newPatch -and (Test-Path $stamp)) {
    $age = (Get-Date) - (Get-Item $stamp).LastWriteTime
    if ($age.TotalDays -lt $MinAgeDays) { exit 0 }
}
if ($newPatch) { Write-Log "New patch $patch (last update was for '$lastPatch')." }

if (Test-Dota) {
    Write-Log "Dota 2 is running; waiting for it to close."
    $deadline = (Get-Date).AddHours($MaxWaitHours)
    while (Test-Dota) {
        if ((Get-Date) -gt $deadline) {
            Write-Log "Dota 2 still running after $MaxWaitHours h; giving up until next trigger."
            exit 1
        }
        Start-Sleep -Seconds $PollSeconds
    }
    Write-Log "Dota 2 closed."
}

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
Get-Date -Format s | Set-Content $stamp
if ($patch) { $patch | Set-Content $patchStamp }
Write-Log "Done."
exit 0
