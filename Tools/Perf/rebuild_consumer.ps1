$ErrorActionPreference = 'Stop'
$consumerRoot = 'D:\UnrealEngine\saskartarad'
$consumerEngine = 'C:\Program Files\Epic Games\UE_5.8\Engine'
$consumerDeadline = (Get-Date).AddMinutes(20)
Write-Output 'Waiting for the user to finish saving and close the editor.'
while (Get-Process UnrealEditor -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $consumerDeadline) { throw 'Editor still open; build was not started.' }
    Start-Sleep -Seconds 2
}
Write-Output 'Editor closed. Building the game module with four compile workers.'
& "$consumerEngine\Build\BatchFiles\Build.bat" UnrealEditor Win64 Development "-Project=$consumerRoot\saskartarad.uproject" -Module=SaskartaCore -WaitMutex -NoHotReloadFromIDE -MaxParallelActions=4 2>&1 | Tee-Object -FilePath "$consumerRoot\Saved\Verification\ConsumerPerf\build.log"
if ($LASTEXITCODE -ne 0) { throw "Native build failed: $LASTEXITCODE" }
Write-Output 'Build succeeded. Reopening the editor.'
Start-Process -FilePath "$consumerEngine\Binaries\Win64\UnrealEditor.exe" -ArgumentList @("$consumerRoot\saskartarad.uproject")
