# schedule_weekly.ps1
# Registers a Windows Task Scheduler job to run the research digest
# every Sunday at 7:00 PM and send it by email.
#
# Run this script ONCE from an elevated PowerShell (Run as Administrator):
#   .\schedule_weekly.ps1

$ProjectDir = "C:\Users\Sejal Kotian\Documents\Penn_Fall_2025\Agentic Workflows\firstagenticworkflow"
$PythonExe  = "$ProjectDir\agaivenv2\Scripts\python.exe"
$Script     = "$ProjectDir\main.py"
$NotesFile  = "$ProjectDir\notes.txt"
$OutputFile = "$ProjectDir\digest.md"
$TaskName   = "WeeklyResearchDigest"

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Script`" --notes-file `"$NotesFile`" --output `"$OutputFile`" --email" `
    -WorkingDirectory $ProjectDir

# Every Sunday at 19:00
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "19:00"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `       # run ASAP if the PC was off at 7pm
    -WakeToRun:$false

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $Action `
    -Trigger    $Trigger `
    -Settings   $Settings `
    -RunLevel   Highest `
    -Force

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host "It will run every Sunday at 7:00 PM." -ForegroundColor Green
Write-Host ""
Write-Host "To run it immediately for a test:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To remove the task:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
