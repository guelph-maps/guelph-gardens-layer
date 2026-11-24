$taskName   = "kk-GuelphGardensLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"`"$projectDir\run-scheduled.cmd`" >> `"$logFile`" 2>&1`""

# Weekly is enough: the roster gains a garden or two a year, and the footprints
# have not changed since 2025-06. The gap page is what moves week to week -- it
# diffs against live OSM. Tuesdays 19:30 keeps clear of every other Guelph and
# Toronto layer's slot (the 16:30 slots Monday to Sunday are taken, and Monday
# 19:30 is the water layer), so no two drive tippecanoe in the same WSL
# instance at once.
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At "19:30"
# Retries live in run-scheduled.cmd, not here: 'update' exits 75 when it sees no
# usable link, and 70 when no Overpass mirror answered and the gap page fell back
# to cached OSM (published first). The wrapper tries either again up to twice, half
# an hour apart, and the 3-hour limit leaves room for that. RestartCount covers only
# a launch that fails; Task Scheduler never re-runs on an exit code.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 3) -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run weekly on Tuesday at 19:30."
Write-Host "Log: $logFile"
