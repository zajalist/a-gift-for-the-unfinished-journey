$ErrorActionPreference = 'Continue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$arch = "D:\UnrealEngine\Builds\saskartarad_development_$stamp"
$log = "D:\UnrealEngine\Builds\logs\saskartarad_development_${stamp}_stage_uat.log"
New-Item -ItemType Directory -Force -Path "D:\UnrealEngine\Builds\logs" | Out-Null
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
"archive $arch"
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\RunUAT.bat" BuildCookRun `
  -project=D:\UnrealEngine\saskartarad\saskartarad.uproject -noP4 -unattended -utf8output -platform=Win64 `
  -clientconfig=Development -skipcook -map=/Game/level/Saskarta_WP -stage -pak -iostore -compressed -prereqs `
  -archive "-archivedirectory=$arch" -AdditionalCookerOptions=-DisablePlugins=HaybaMCPToolkit *> $log
$code = $LASTEXITCODE
"exit $code"
Get-Content $log -Tail 6
$game = Join-Path $arch 'Windows\saskartarad'
if ($code -eq 0 -and (Test-Path $game)) {
  $dst = Join-Path $game 'docs\story'
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  Copy-Item D:\UnrealEngine\saskartarad\docs\story\*.json $dst
  "docs copied: $((Get-ChildItem $dst).Count) files"
  Get-ChildItem (Join-Path $arch 'Windows') -Filter *.exe | Select-Object -ExpandProperty FullName
}
