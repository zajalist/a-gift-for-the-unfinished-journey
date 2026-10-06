$ErrorActionPreference = 'Continue'
$S = "D:\UnrealEngine\saskartarad\Tools\Package"
$WT = "D:\UnrealEngine\sask_snapshot"
Set-Location D:\UnrealEngine\saskartarad
# 1. A clean worktree of the last commit, for the game code only.
# (reuse an existing snapshot worktree)
git -c core.longpaths=true worktree add --detach $WT HEAD 2>&1 | Select-Object -Last 1; New-Item -ItemType Junction -Path "$WT\Plugins\HaybaMCPToolkit" -Target "D:\UnrealEngine\saskartarad\Plugins\HaybaMCPToolkit" | Out-Null
$head = git rev-parse --short HEAD
"snapshot $head"
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" saskartarad Win64 Development "-Project=$WT\saskartarad.uproject" -WaitMutex 2>&1 | Select-String "error|Result:" | Select-Object -Last 6
$snapExe = "$WT\Binaries\Win64\saskartarad.exe"
if (-not (Test-Path $snapExe)) { "SNAPSHOT BUILD FAILED"; exit 1 }
# 2. Cook + stage the current content in the main tree (skip its build: its code is mid-edit by the lanes).
$stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$arch = "D:\UnrealEngine\Builds\saskartarad_development_$stamp"
$log = "D:\UnrealEngine\Builds\logs\saskartarad_development_${stamp}_snap_uat.log"
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\RunUAT.bat" BuildCookRun `
  -project=D:\UnrealEngine\saskartarad\saskartarad.uproject -noP4 -unattended -utf8output -platform=Win64 `
  -clientconfig=Development -cook -map=/Game/level/Saskarta_WP -AdditionalCookerOptions=-DisablePlugins=HaybaMCPToolkit *> $log
"cook exit $LASTEXITCODE"
Start-Sleep -Seconds 20
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\RunUAT.bat" BuildCookRun `
  -project=D:\UnrealEngine\saskartarad\saskartarad.uproject -noP4 -unattended -utf8output -platform=Win64 `
  -clientconfig=Development -skipcook -map=/Game/level/Saskarta_WP -stage -pak -iostore -compressed -prereqs `
  -archive "-archivedirectory=$arch" *>> $log
"stage exit $LASTEXITCODE"
$game = Join-Path $arch 'Windows\saskartarad'
if (-not (Test-Path $game)) { "STAGE FAILED"; Get-Content $log -Tail 8; exit 1 }
# 3. The clean snapshot's game binary replaces whatever the lanes last compiled.
Copy-Item $snapExe (Join-Path $game 'Binaries\Win64\saskartarad.exe') -Force
if (Test-Path "$WT\Binaries\Win64\saskartarad.pdb") { Copy-Item "$WT\Binaries\Win64\saskartarad.pdb" (Join-Path $game 'Binaries\Win64\') -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $game 'docs\story') | Out-Null
Copy-Item D:\UnrealEngine\saskartarad\docs\story\*.json (Join-Path $game 'docs\story')
"built $arch (code $head)"
