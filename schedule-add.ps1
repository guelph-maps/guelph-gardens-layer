$taskName   = "kk-GuelphGardensLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c cd /d `"$projectDir`" && python run.py update >> `"$logFile`" 2>&1"

# Weekly is enough: the roster gains a garden or two a year, and the footprints
# have not changed since 2025-06. The gap page is what moves week to week -- it
# diffs against live OSM. Tuesdays 19:30 keeps clear of every other Guelph and
# Toronto layer's slot (the 16:30 slots Monday to Sunday are taken, and Monday
# 19:30 is the water layer), so no two drive tippecanoe in the same WSL
# instance at once.
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At "19:30"
# Restart on failure. 'update' exits 75 as soon as it sees no usable link
# instead of blocking on one (the ExecutionTimeLimit would kill a long wait
# anyway), so three tries half an hour apart turn a dead link at 19:30 into a
# run by 21:00 rather than a seven-day gap. Still clear of the 23:00 quiet
# window.
#
# It also exits 70 when no Overpass mirror answered and the gap page had to fall
# back to cached OSM. That publishes first, so the retry costs a rebuild and not
# the tiles.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run weekly on Tuesday at 19:30."
Write-Host "Log: $logFile"
