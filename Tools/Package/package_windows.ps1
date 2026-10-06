<#
.SYNOPSIS
  Package saskartarad for Windows (Development and/or Shipping), with the bundled PSO cache flow.

.DESCRIPTION
  Wraps RunUAT BuildCookRun: -build -cook -stage -pak -iostore -compressed -prereqs -archive.
  See Tools/Package/README.md (disk, time, what to click) and Tools/Package/PSO_CACHE.md (the PSO flow).

  It REFUSES to run when:
    - Saved/Locks/binaries.lock exists (a build or test run holds the binaries),
    - an UnrealEditor process for this project is running (editor, -game standalone, or commandlet):
      a cook with the editor open competes for the DDC, RAM and every core. Close it first,
    - another UAT/UBT run is active,
    - the archive drive or the Zen/DDC drive has less free space than -MinFreeGB / -MinFreeDdcGB.

  Modes:
    (default)   Package -Config Development | Shipping | Both into -ArchiveRoot.
                If Build/Windows/PipelineCaches/*saskartarad_PCD3D_SM6.spc exists, the cook bundles it.
    -LogPSO     Development recording build: stable shader keys forced on, the cook's .shk files
                copied next to the archive, and Record-PSO.bat (runs the exe with -logPSO) written.
    -ExpandPSO  Turn the recordings into Build/Windows/PipelineCaches/saskartarad_PCD3D_SM6.spc
                (ShaderPipelineCacheTools expand). No cook. Then package again to bundle it.
    -DryRun     Run the checks and print the commands; start nothing.

.EXAMPLE
  .\Tools\Package\package_windows.ps1 -DryRun
  .\Tools\Package\package_windows.ps1 -LogPSO
  .\Tools\Package\package_windows.ps1 -ExpandPSO -RecordingsDir D:\UnrealEngine\Builds\saskartarad_psorec_20261001-2000\Windows\saskartarad\Saved\CollectedPSOs -KeysDir D:\UnrealEngine\Builds\saskartarad_psorec_20261001-2000\_pso\keys
  .\Tools\Package\package_windows.ps1 -Config Both
#>
[CmdletBinding()]
param(
    [ValidateSet('Development', 'Shipping', 'Both')]
    [string]$Config = 'Development',

    [switch]$LogPSO,
    [switch]$ExpandPSO,
    [string]$RecordingsDir,
    [string]$KeysDir,

    [string]$ArchiveRoot = 'D:\UnrealEngine\Builds',
    [string[]]$Maps = @('/Game/level/Saskarta_WP'),
    [string]$EngineDir = 'C:\Program Files\Epic Games\UE_5.8',
    [string]$ShaderFormat = 'PCD3D_SM6',

    [int]$MinFreeGB = 40,        # on the archive drive (staging + archive + game build)
    [int]$MinFreeDdcGB = 25,     # on the drive holding the Zen store (cooked output + DDC)

    [ValidateRange(1, 64)]
    [int]$MaxParallelActions = 4,

    [switch]$SkipCook,           # reuse the last cook (Saved/Cooked + Zen); only rebuild/stage/pak
    [switch]$Distribution,       # Shipping only: -distribution -nodebuginfo
    [switch]$NormalPriority,     # default runs UAT at BelowNormal so the PC stays usable
    [switch]$AllowEditor,        # 2026-10-05: package while the editor stays open (playtest in parallel)
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------------------------
$ProjectDir  = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ProjectName = 'saskartarad'
$UProject    = Join-Path $ProjectDir "$ProjectName.uproject"
$RunUAT      = Join-Path $EngineDir 'Engine\Build\BatchFiles\RunUAT.bat'
$EditorCmd   = Join-Path $EngineDir 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
$LockFile    = Join-Path $ProjectDir 'Saved\Locks\binaries.lock'
$StablePCDir = Join-Path $ProjectDir 'Build\Windows\PipelineCaches'
$SpcName     = "${ProjectName}_${ShaderFormat}.spc"
$SpcPath     = Join-Path $StablePCDir $SpcName
$CookedDir   = Join-Path $ProjectDir 'Saved\Cooked\Windows'
$ZenDataDir  = Join-Path $env:LOCALAPPDATA 'UnrealEngine\Common\Zen\Data'
$Stamp       = Get-Date -Format 'yyyyMMdd-HHmm'
$LogDir      = Join-Path $ArchiveRoot 'logs'

function Write-Section([string]$Text) {
    Write-Host ''
    Write-Host ('==== ' + $Text + ' ').PadRight(96, '=') -ForegroundColor Cyan
}

function Get-FreeGB([string]$Path) {
    $root = [System.IO.Path]::GetPathRoot($Path)
    $drive = New-Object System.IO.DriveInfo($root)
    return [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
}

function Get-DirGB([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    if (-not $sum) { return 0 }
    return [math]::Round($sum / 1GB, 2)
}

function Show-Disk([string]$When) {
    Write-Section "Disk free ($When)"
    $zenRoot = [System.IO.Path]::GetPathRoot($ZenDataDir)
    $rows = @(
        @{ Name = "Archive drive  ($([System.IO.Path]::GetPathRoot($ArchiveRoot)))"; GB = (Get-FreeGB $ArchiveRoot) },
        @{ Name = "Project drive  ($([System.IO.Path]::GetPathRoot($ProjectDir)))"; GB = (Get-FreeGB $ProjectDir) },
        @{ Name = "Zen/DDC drive  ($zenRoot)"; GB = (Get-FreeGB $ZenDataDir) }
    )
    foreach ($r in $rows) { Write-Host ("  {0,-26} {1,8} GB free" -f $r.Name, $r.GB) }
}

# Read-only scan of the project config for [DevOptions.Shaders] NeedsShaderStableKeys=true.
function Test-IniHasStableKeys {
    $files = @(
        (Join-Path $ProjectDir 'Config\DefaultEngine.ini'),
        (Join-Path $ProjectDir 'Config\Windows\WindowsEngine.ini')
    )
    foreach ($f in $files) {
        if (-not (Test-Path $f)) { continue }
        $inSection = $false
        foreach ($line in Get-Content -LiteralPath $f) {
            $t = $line.Trim()
            if ($t -match '^\[(.+)\]$') { $inSection = ($Matches[1] -eq 'DevOptions.Shaders'); continue }
            if ($inSection -and $t -match '^b?NeedsShaderStableKeys\s*=\s*(true|1)\s*$') { return $true }
        }
    }
    return $false
}

# ---------------------------------------------------------------------------------------------
# Preflight: refuse if the editor / a build holds the project, or the disks are too full
# ---------------------------------------------------------------------------------------------
function Test-Preflight {
    $problems = New-Object System.Collections.Generic.List[string]
    $warnings = New-Object System.Collections.Generic.List[string]

    foreach ($p in @($UProject, $RunUAT, $EditorCmd)) {
        if (-not (Test-Path $p)) { $problems.Add("Missing: $p") }
    }

    if (Test-Path $LockFile) {
        $holder = (Get-Content -LiteralPath $LockFile -ErrorAction SilentlyContinue) -join ' '
        $problems.Add("Saved\Locks\binaries.lock exists (held by: $holder). Wait for that build/test to finish.")
    }

    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -match '^UnrealEditor' })
    foreach ($p in $procs) {
        $cl = [string]$p.CommandLine
        if ([string]::IsNullOrEmpty($cl)) {
            $problems.Add("$($p.Name) (PID $($p.ProcessId)) is running and its command line is unreadable (elevated?). Close it or check it is not this project.")
        }
        elseif ($cl -match [regex]::Escape($ProjectName) -and $AllowEditor) {
            $warnings.Add("$($p.Name) (PID $($p.ProcessId)) has this project open; packaging anyway (-AllowEditor).")
        }
        elseif ($cl -match [regex]::Escape($ProjectName)) {
            $problems.Add("$($p.Name) (PID $($p.ProcessId)) has this project open. Close the editor (and any -game window) first.")
        }
        else {
            $warnings.Add("$($p.Name) (PID $($p.ProcessId)) is running another project; it will compete for CPU/RAM.")
        }
    }

    $builders = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'AutomationTool\.dll|UnrealBuildTool\.dll|\\UnrealBuildTool\.exe') })
    foreach ($b in $builders) {
        $problems.Add("A UAT/UBT process is running (PID $($b.ProcessId), $($b.Name)). Let it finish first.")
    }
    $running = @(Get-Process -Name $ProjectName, "$ProjectName-Win64-Shipping" -ErrorAction SilentlyContinue)
    foreach ($r in $running) {
        $warnings.Add("A packaged $($r.ProcessName).exe is running (PID $($r.Id)); quit it if it runs from the archive folder.")
    }

    if (-not $ExpandPSO) {
        $archFree = Get-FreeGB $ArchiveRoot
        if ($archFree -lt $MinFreeGB) {
            $problems.Add("Only $archFree GB free on the archive drive; need $MinFreeGB GB (-MinFreeGB). Delete old builds in $ArchiveRoot or pick another -ArchiveRoot.")
        }
        $ddcFree = Get-FreeGB $ZenDataDir
        if ($ddcFree -lt $MinFreeDdcGB) {
            $problems.Add("Only $ddcFree GB free on the Zen/DDC drive ($ZenDataDir); need $MinFreeDdcGB GB (-MinFreeDdcGB).")
        }
    }

    Write-Section 'Preflight'
    foreach ($w in $warnings) { Write-Host "  WARN  $w" -ForegroundColor Yellow }
    foreach ($p in $problems) { Write-Host "  STOP  $p" -ForegroundColor Red }
    if ($problems.Count -eq 0) { Write-Host '  OK    no editor/build holds the project; disk thresholds met.' -ForegroundColor Green }
    return ($problems.Count -eq 0)
}

function Invoke-Native([string]$Exe, [string[]]$ArgList, [string]$LogPath) {
    Write-Host ''
    Write-Host '  Command:' -ForegroundColor Gray
    Write-Host ('  & "' + $Exe + '" ' + ($ArgList -join ' ')) -ForegroundColor Gray
    Write-Host "  Log: $LogPath" -ForegroundColor Gray
    if ($DryRun) { Write-Host '  (dry run: not started)' -ForegroundColor Yellow; return 0 }

    New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # native stderr lines must not become terminating errors (PS 5.1)
    try {
        & $Exe @ArgList 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $LogPath | Out-Host
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
    $sw.Stop()
    Write-Host ("  Exit code {0} after {1:hh\:mm\:ss}" -f $code, $sw.Elapsed) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Red' })
    return $code
}

# ---------------------------------------------------------------------------------------------
# Mode: -ExpandPSO (recordings + stable keys -> Build/Windows/PipelineCaches/<name>.spc)
# ---------------------------------------------------------------------------------------------
function Invoke-ExpandPSO {
    if (-not $RecordingsDir -or -not (Test-Path $RecordingsDir)) { throw "-RecordingsDir is required and must exist (the packaged game's Saved\CollectedPSOs folder)." }
    if (-not $KeysDir -or -not (Test-Path $KeysDir)) { throw "-KeysDir is required and must exist (the _pso\keys folder next to the recording build, or Saved\Cooked\Windows\$ProjectName\Metadata\PipelineCaches)." }

    $recs = @(Get-ChildItem -LiteralPath $RecordingsDir -Recurse -File -Filter '*.rec.upipelinecache')
    $keys = @(Get-ChildItem -LiteralPath $KeysDir -Recurse -File -Filter '*.shk' | Where-Object { $_.Name -match [regex]::Escape($ShaderFormat) })
    Write-Section 'Expand PSO recordings'
    Write-Host "  Recordings ($($recs.Count)):"; $recs | ForEach-Object { Write-Host ("    {0}  {1:N0} KB" -f $_.Name, ($_.Length / 1KB)) }
    Write-Host "  Stable keys for $ShaderFormat ($($keys.Count)):"; $keys | ForEach-Object { Write-Host "    $($_.Name)" }
    if ($recs.Count -eq 0) { throw "No *.rec.upipelinecache under $RecordingsDir. Did the -logPSO run quit normally (or run r.ShaderPipelineCache.Save)?" }
    if ($keys.Count -eq 0) { throw "No *$ShaderFormat*.shk under $KeysDir. The recording build must be cooked with NeedsShaderStableKeys (the -LogPSO mode forces it)." }

    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $StablePCDir | Out-Null }
    if (Test-Path $SpcPath) {
        # Back up OUTSIDE Build/Windows/PipelineCaches: the cooker globs that folder recursively for *.spc.
        $bak = Join-Path $ProjectDir "Saved\PSO\backup\${Stamp}_$SpcName"
        if (-not $DryRun) {
            New-Item -ItemType Directory -Force -Path (Split-Path $bak) | Out-Null
            Copy-Item -LiteralPath $SpcPath -Destination $bak -Force
        }
        Write-Host "  Existing $SpcName backed up to $bak"
    }

    # No embedded quotes: PowerShell quotes any argument that contains a space by itself.
    $argList = @($UProject, '-run=ShaderPipelineCacheTools', 'expand')
    $argList += @($recs | ForEach-Object { $_.FullName })
    $argList += @($keys | ForEach-Object { $_.FullName })
    $argList += @($SpcPath, '-unattended', '-nop4', '-nosplash', '-nullrhi', '-DisablePlugins=HaybaMCPToolkit')
    $log = Join-Path $LogDir "expandpso_$Stamp.log"
    $code = Invoke-Native $EditorCmd $argList $log
    if ($DryRun) { return 0 }

    if ($code -ne 0 -or -not (Test-Path $SpcPath) -or (Get-Item $SpcPath).Length -eq 0) {
        Write-Host "  Expand FAILED: see $log" -ForegroundColor Red
        return 1
    }
    Write-Host ''
    Select-String -LiteralPath $log -Pattern 'Loaded \d+ PSOs|Wrote|PSOs total|binary PSOs|Error' | Select-Object -First 20 | ForEach-Object { Write-Host "  $($_.Line.Trim())" }
    Write-Host ("  Wrote {0} ({1:N0} KB). Commit it by pathspec, then package again to bundle it." -f $SpcPath, ((Get-Item $SpcPath).Length / 1KB)) -ForegroundColor Green
    return 0
}

# ---------------------------------------------------------------------------------------------
# Mode: package (Development / Shipping / Both, or the -LogPSO recording build)
# ---------------------------------------------------------------------------------------------
function Get-UatArgs([string]$ClientConfig, [string]$ArchiveDir, [bool]$DoCook, [string]$CookerOptions, [string[]]$IniOverrides) {
    $a = @(
        'BuildCookRun',
        "-project=$UProject",
        '-noP4', '-unattended', '-utf8output',
        '-platform=Win64', "-clientconfig=$ClientConfig",
        '-build', "-UbtArgs=-MaxParallelActions=$MaxParallelActions"
    )
    if ($DoCook) { $a += '-cook' } else { $a += '-skipcook' }
    $a += @(
        ('-map=' + ($Maps -join '+')),
        '-stage', '-pak', '-iostore', '-compressed', '-prereqs',
        '-archive', "-archivedirectory=$ArchiveDir"
    )
    if ($ClientConfig -eq 'Shipping' -and $Distribution) { $a += @('-distribution', '-nodebuginfo') }
    if ($CookerOptions) { $a += "-AdditionalCookerOptions=$CookerOptions" }
    # UAT forwards every -ini:<File>:[Section]:Key=Value to the cooker (CookCommand.Automation.cs, ConfigOverrideParams).
    foreach ($o in $IniOverrides) { $a += $o }
    return $a
}

function Invoke-Package {
    $configs = @(switch ($Config) { 'Both' { 'Development', 'Shipping' } default { $Config } })
    if ($LogPSO) {
        if ($Config -ne 'Development') { Write-Host '  -LogPSO records with a Development build; ignoring -Config.' -ForegroundColor Yellow }
        $configs = @('Development')
    }

    # Cooker options: keep the Hayba MCP server off the cook commandlet. Stable shader keys are
    # needed to record (the .shk files) AND to bundle a .spc (the cooker skips the .spc without
    # them), so force them with a config override until the line is in DefaultEngine.ini.
    $cookerOptString = '-DisablePlugins=HaybaMCPToolkit'
    $iniKeys = Test-IniHasStableKeys
    $iniOverrides = @()
    if (-not $iniKeys) { $iniOverrides += '-ini:Engine:[DevOptions.Shaders]:NeedsShaderStableKeys=true' }

    Write-Section 'Plan'
    Write-Host "  Project        $UProject"
    Write-Host "  Configs        $($configs -join ', ')$(if ($LogPSO) { '  (PSO recording build)' })"
    Write-Host "  Maps           $($Maps -join ', ')"
    Write-Host "  Archive root   $ArchiveRoot"
    Write-Host "  Stable keys    $(if ($iniKeys) { 'on (ini)' } else { 'on (forced by -ini: override; add the ini line, see README)' })"
    $spcFound = @()
    if (Test-Path $StablePCDir) { $spcFound = @(Get-ChildItem -LiteralPath $StablePCDir -Recurse -File -Filter "*$SpcName") }
    if ($spcFound.Count -gt 0) {
        Write-Host "  Bundled PSOs   YES: $($spcFound[0].FullName) ($([math]::Round($spcFound[0].Length / 1KB)) KB) will be built into the pak" -ForegroundColor Green
    }
    else {
        Write-Host "  Bundled PSOs   none yet ($SpcPath missing): this build relies on PSO precaching only" -ForegroundColor Yellow
    }
    Write-Host "  Content size   $(Get-DirGB (Join-Path $ProjectDir 'Content')) GB raw"

    $archives = @()
    $cooked = $SkipCook.IsPresent
    $rc = 0
    foreach ($cfg in $configs) {
        $name = if ($LogPSO) { "${ProjectName}_psorec_$Stamp" } else { "${ProjectName}_$($cfg.ToLower())_$Stamp" }
        $archiveDir = Join-Path $ArchiveRoot $name
        $archives += $archiveDir
        Write-Section "BuildCookRun $cfg -> $archiveDir"
        $uatArgs = Get-UatArgs $cfg $archiveDir (-not $cooked) $cookerOptString $iniOverrides
        $rc = Invoke-Native $RunUAT $uatArgs (Join-Path $LogDir "$name`_uat.log")
        if ($rc -ne 0) { Write-Host "  BuildCookRun $cfg failed (exit $rc). Nothing further runs." -ForegroundColor Red; break }
        $cooked = $true   # the second config (Both) reuses this cook

        if (-not $DryRun) {
            $exe = Join-Path $archiveDir "Windows\$ProjectName.exe"
            Write-Host ("  Archive size {0} GB; exe: {1} ({2})" -f (Get-DirGB $archiveDir), $exe, $(if (Test-Path $exe) { 'found' } else { 'NOT FOUND' }))
        }
    }

    if ($rc -eq 0 -and $LogPSO) { Complete-LogPSO $archives[0] }
    return $rc
}

function Complete-LogPSO([string]$ArchiveDir) {
    Write-Section 'PSO recording build: next steps'
    $keysOut = Join-Path $ArchiveDir '_pso\keys'
    $recDir  = Join-Path $ArchiveDir "Windows\$ProjectName\Saved\CollectedPSOs"
    $bat     = Join-Path $ArchiveDir 'Record-PSO.bat'
    if (-not $DryRun) {
        # Keep the stable keys WITH this build: each recording must be expanded with the keys of the cook it came from.
        $shk = @()
        if (Test-Path $CookedDir) { $shk = @(Get-ChildItem -LiteralPath $CookedDir -Recurse -File -Filter '*.shk') }
        if ($shk.Count -eq 0) {
            Write-Host "  WARNING: no .shk stable-key files under $CookedDir. The expand step cannot work; check the cook log for NeedsShaderStableKeys." -ForegroundColor Red
        }
        else {
            New-Item -ItemType Directory -Force -Path $keysOut | Out-Null
            $shk | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $keysOut -Force }
            Write-Host "  Copied $($shk.Count) stable-key file(s) to $keysOut"
        }
        @(
            '@echo off',
            'rem PSO recording run (Tools/Package/PSO_CACHE.md). Play the route, then quit from the menu so the recording is written.',
            'rem Recordings land in Windows\saskartarad\Saved\CollectedPSOs\*.rec.upipelinecache next to this file.',
            'start "" "%~dp0Windows\saskartarad.exe" -logPSO'
        ) | Set-Content -LiteralPath $bat -Encoding ASCII
        Write-Host "  Wrote $bat"
    }
    Write-Host "  1. Run $bat and play the route in PSO_CACHE.md (about 20 min). Quit from the menu."
    Write-Host "  2. Recordings: $recDir"
    Write-Host '  3. Expand them into the stable cache (editor closed):'
    Write-Host "     .\Tools\Package\package_windows.ps1 -ExpandPSO -RecordingsDir `"$recDir`" -KeysDir `"$keysOut`""
    Write-Host "  4. Commit Build\Windows\PipelineCaches\$SpcName by pathspec, then package again (-Config Development or Both)."
}

# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------
if ($LogPSO -and $ExpandPSO) { throw 'Use -LogPSO (build a recording package) or -ExpandPSO (process recordings), not both.' }

Show-Disk 'before'
$ok = Test-Preflight
if (-not $ok -and -not $DryRun) {
    Write-Host ''
    Write-Host 'Refusing to run. Fix the STOP items above and run again.' -ForegroundColor Red
    exit 2
}
if (-not $ok) { Write-Host '  (dry run: continuing to print the commands despite STOP items)' -ForegroundColor Yellow }

$oldPriority = $null
if (-not $NormalPriority -and -not $DryRun) {
    # Child processes (UAT, UBT, the cooker, ShaderCompileWorkers) inherit this priority class.
    $me = Get-Process -Id $PID
    $oldPriority = $me.PriorityClass
    $me.PriorityClass = 'BelowNormal'
}

$exitCode = 0
try {
    if ($ExpandPSO) { $exitCode = Invoke-ExpandPSO } else { $exitCode = Invoke-Package }
}
finally {
    if ($oldPriority) { (Get-Process -Id $PID).PriorityClass = $oldPriority }
    Show-Disk 'after'
}
exit $exitCode
