param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [Parameter(Mandatory = $true)]
    [string]$BuildManifest,
    [string]$EngineRoot = 'C:\Program Files\Epic Games\UE_5.8\Engine'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ArchivePath = [System.IO.Path]::GetFullPath($Destination)
if ($ArchivePath.StartsWith($ProjectRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Archive destination must be outside the project tree.'
}
if (-not $ArchivePath.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Archive destination must end in .zip.'
}
if (Test-Path -LiteralPath $ArchivePath) {
    throw "Archive already exists: $ArchivePath"
}

$ManifestTool = Join-Path $PSScriptRoot 'project_archive_manifest.py'
$BindingPath = (Resolve-Path -LiteralPath $BuildManifest).Path
$Work = "$ArchivePath.inputs"
if (Test-Path -LiteralPath $Work) { throw "Archive preparation already exists: $Work" }
$Maps = Get-Content -LiteralPath (Join-Path $ProjectRoot 'Config/DefaultEngine.ini')
foreach ($Setting in @('EditorStartupMap=/Game/level/Saskarta_WP.Saskarta_WP', 'GameDefaultMap=/Game/level/Saskarta_WP.Saskarta_WP')) {
    if (-not ($Maps -contains $Setting)) { throw "Map config missing: $Setting" }
}
$Actors = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'Content/__ExternalActors__/level/Saskarta_WP') -Recurse -File -Filter '*.uasset')
if ($Actors.Count -lt 4000) { throw "Unexpectedly few saved Saskarta World Partition actors: $($Actors.Count)" }
$TripoAudit = Join-Path $ProjectRoot 'Saved/Tripo/saved_level_coverage.json'
& python (Join-Path $ProjectRoot 'Tools/Tripo/audit_saved_level.py') --output $TripoAudit --min-types 24
if ($LASTEXITCODE -ne 0) { throw 'Approved Tripo meshes are not all referenced by saved Saskarta_WP actor packages.' }

# Hash current inputs against the snapshot bound to a successful fresh UAT build.
# Prepare an archive-only uproject overlay; never edit the working project or copy engine plugins.
& python $ManifestTool --project $ProjectRoot prepare --engine $EngineRoot --binding $BindingPath --work $Work
if ($LASTEXITCODE -ne 0) { throw 'Project matching, dependency, source/provenance or baked-asset validation failed.' }
$FileList = Join-Path $Work 'files.nul'
$InputManifest = Join-Path $Work 'PROJECT_ARCHIVE_MANIFEST.json'

$Parent = Split-Path -Parent $ArchivePath
New-Item -ItemType Directory -Path $Parent -Force | Out-Null
Push-Location $ProjectRoot
try {
    # Exact file allowlist excludes nested plugin Intermediate/DDC/cache directories.
    # NUL-delimited paths avoid tar option/whitespace interpretation.
    & tar.exe --format=zip --options zip:compression=deflate,zip:compression-level=1 -cf $ArchivePath -C $ProjectRoot --null -T $FileList -C $Work 'saskartarad.uproject' 'PROJECT_ARCHIVE_DEPENDENCIES.json' 'PROJECT_ARCHIVE_MANIFEST.json'
    if ($LASTEXITCODE -ne 0) { throw "tar failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
& python $ManifestTool --project $ProjectRoot verify-zip --archive $ArchivePath --manifest $InputManifest --check-current
if ($LASTEXITCODE -ne 0) { throw 'Complete ZIP member CRC/hash or final matching-source validation failed; preserve this unaccepted artifact.' }

$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$Archive = Get-Item -LiteralPath $ArchivePath
$Manifest = [ordered]@{
    archive = $Archive.Name
    bytes = $Archive.Length
    sha256 = $Hash
    created_utc = (Get-Date).ToUniversalTime().ToString('o')
    project = 'saskartarad'
    engine = 'Unreal Engine 5.8'
    zip_compression = 'deflate level 1'
    default_editor_map = '/Game/level/Saskarta_WP.Saskarta_WP'
    saved_world_partition_actor_packages = $Actors.Count
    tripo_saved_level_audit = 'Saved/Tripo/saved_level_coverage.json'
    input_manifest = 'PROJECT_ARCHIVE_MANIFEST.json'
    input_manifest_sha256 = (Get-FileHash -LiteralPath $InputManifest -Algorithm SHA256).Hash.ToLowerInvariant()
    build_binding_sha256 = (Get-FileHash -LiteralPath $BindingPath -Algorithm SHA256).Hash.ToLowerInvariant()
    excluded_generated_at_any_depth = @('.git', 'Intermediate', 'DerivedDataCache', '__pycache__', '.pytest_cache', '*.bak*', '*.pyc')
    editor_tools_disabled_in_archive_only = @('Aura', 'AIAssistant', 'InEditorDocumentation')
    extracted_project_and_gameplay_acceptance = 'pending; run verify-extracted with the external input manifest, then open/build/launch'
}
$ManifestPath = "$ArchivePath.manifest.json"
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding utf8
"$Hash  $($Archive.Name)" | Set-Content -LiteralPath "$ArchivePath.sha256" -Encoding ascii
Write-Output "Archive: $ArchivePath"
Write-Output "Size: $([math]::Round($Archive.Length / 1GB, 2)) GB"
Write-Output "Saved actor packages: $($Actors.Count)"
Write-Output "SHA-256: $Hash"
