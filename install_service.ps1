$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $ProjectDir "run.ps1"
$TaskName = "ChungKhoanServer_AutoStart"

Write-Host "Creating Scheduled Task to run the server in the background..." -ForegroundColor Cyan

# Define the action: Run powershell silently with our run.ps1 script
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`""

# Define the trigger: At system startup or user logon
# We use AtLogon to ensure the user's environment variables (like Conda) are fully loaded
$Trigger = New-ScheduledTaskTrigger -AtLogon

# Configure settings: Require network connection, don't stop on battery
$Settings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries -DontStopOnIdleEnd -ExecutionTimeLimit 0

# Register the task for the current user
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest -Force
    Write-Host "Service task '$TaskName' has been successfully created!" -ForegroundColor Green
    Write-Host "The server will now automatically start in the background when you log in and have an internet connection." -ForegroundColor Green
}
catch {
    Write-Host "Failed to create task. Please ensure you are running this as Administrator." -ForegroundColor Red
    throw
}
