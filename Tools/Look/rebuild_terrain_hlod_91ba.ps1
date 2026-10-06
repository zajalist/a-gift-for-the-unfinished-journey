# Rebuild only the confirmed merged HLOD actor after its material/merge rule is fixed.
# This script is intentionally inert without -Execute. Close Unreal Editor first.
param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$project = Join-Path $projectRoot 'saskartarad.uproject'
$editor = 'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
$actorPackage = Join-Path $projectRoot 'Content\__ExternalActors__\level\Saskarta_WP\6\DF\5RVX94A0O25QQHIC5POROE.uasset'
$label = 'Saskarta_WP_HLODLayer_Merged/Saskarta_WP_HLODLayer_Instanced_L3_X1_Y2'
$layer = 'Saskarta_WP_HLODLayer_Merged'
$outDir = Join-Path $projectRoot 'Saved\Verification\terrain_seam_20261002\hlod_91ba_rebuild'
$args = @(
    $project,
    '/Game/level/Saskarta_WP',
    '-run=WorldPartitionBuilderCommandlet',
    '-Builder=WorldPartitionHLODsBuilder',
    "-BuildSingleHLOD=$label",
    "-BuildHLODLayer=$layer",
    '-AllowCommandletRendering',
    '-SCCProvider=None',
    '-DisablePlugins=HaybaMCPToolkit',
    '-unattended'
)

if (-not (Test-Path -LiteralPath $project) -or -not (Test-Path -LiteralPath $editor) -or -not (Test-Path -LiteralPath $actorPackage)) {
    throw 'Project, editor, or exact HLOD actor package missing.'
}
Write-Host "Exact actor: $label"
Write-Host "Exact package: $actorPackage"
Write-Host "Command: $editor $($args -join ' ')"
if (-not $Execute) {
    Write-Host 'Dry run only. Supply -Execute after same-view diagnosis and material/merge repair.'
    return
}
if (Get-Process -Name UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue) {
    throw 'Close Unreal Editor and other editor commandlets before this one-actor HLOD rebuild.'
}

New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$backup = Join-Path $outDir '5RVX94A0O25QQHIC5POROE.before.uasset'
$log = Join-Path $outDir 'build.log'
$before = (Get-FileHash -Algorithm SHA256 -LiteralPath $actorPackage).Hash
Copy-Item -LiteralPath $actorPackage -Destination $backup -Force
& $editor @args 2>&1 | Tee-Object -FilePath $log
$exit = $LASTEXITCODE
$output = Get-Content -LiteralPath $log -Raw
$after = (Get-FileHash -Algorithm SHA256 -LiteralPath $actorPackage).Hash
$result = [ordered]@{
    actor = $label
    package = $actorPackage
    backup = $backup
    before_sha256 = $before
    after_sha256 = $after
    exit_code = $exit
    one_actor_banner = $output.Contains('Building 1 HLOD actors')
    one_actor_step = $output.Contains('[1 / 1]')
    failure_in_log = [bool]($output -match 'Fatal error|Assertion failed|HLOD build cancelled|LogWorldPartitionHLODsBuilder: Error:|LogWorldPartitionHLODUtilities: Error:')
}
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outDir 'receipt.json') -Encoding utf8
if ($exit -ne 0 -or -not $result.one_actor_banner -or -not $result.one_actor_step -or $result.failure_in_log) {
    throw "One-actor HLOD build did not pass its log gate. Inspect $log and restore $backup if required."
}
Write-Host "One-actor build passed; package SHA256: $after"
