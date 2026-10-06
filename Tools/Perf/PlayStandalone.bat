@echo off
rem Play Saskarta as a standalone game (smooth; one world in memory), not play-in-editor.
if exist "D:\UnrealEngine\saskartarad\Saved\Locks\binaries.lock" (
  echo A build or test run holds Saved\Locks\binaries.lock - wait for it to finish, then try again.
  type "D:\UnrealEngine\saskartarad\Saved\Locks\binaries.lock"
  pause
  exit /b 1
)
start "" "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "D:\UnrealEngine\saskartarad\saskartarad.uproject" /Game/level/Saskarta_WP -game -fullscreen -nosplash
