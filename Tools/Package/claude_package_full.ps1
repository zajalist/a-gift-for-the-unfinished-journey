$S = $PSScriptRoot
# Build + cook; if the cook finished every package but logged errors (exit 25), stage the finished cook.
$out = & powershell -ExecutionPolicy Bypass -File (Join-Path $S 'claude_package_now.ps1')
$out | Select-Object -Last 3
$arch = ($out | Where-Object { $_ -like 'archive *' } | Select-Object -First 1) -replace '^archive ', ''
if (-not $arch) { throw 'Cook did not report an archive path.' }
if (-not (Test-Path (Join-Path $arch 'Windows\saskartarad.exe'))) {
  if (-not ($out -match '^exit 25$')) { throw "Cook failed without a complete archive: $($out | Select-Object -Last 3)" }
  "cook flagged errors: staging the finished cook"
  Start-Sleep -Seconds 20
  & powershell -ExecutionPolicy Bypass -File (Join-Path $S 'claude_package_stage.ps1') | Select-Object -Last 3
}
