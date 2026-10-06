# Prepare native Unreal Insights exports. Launch is explicit and should occur after PIE ends.
# The script never calls the editor, modifies the game, terminates processes, or runs tests.
param(
    [Parameter(Mandatory=$true)][string]$TracePath,
    [string]$Label = 'targeted_cpu',
    [double]$StartSeconds = 0,
    [double]$EndSeconds = 45,
    [switch]$Launch
)
$ErrorActionPreference='Stop'
if ($Label -notmatch '^[a-zA-Z0-9_-]{1,60}$') { throw 'Label must be a short filename-safe value.' }
if ([double]::IsNaN($StartSeconds) -or [double]::IsInfinity($StartSeconds) -or [double]::IsNaN($EndSeconds) -or [double]::IsInfinity($EndSeconds) -or $StartSeconds -lt 0 -or $EndSeconds -le $StartSeconds -or ($EndSeconds-$StartSeconds) -gt 90) {
    throw 'Export interval must be positive, finite, and at most 90 seconds.'
}
$resolvedTrace=(Resolve-Path -LiteralPath $TracePath).Path
if ([IO.Path]::GetExtension($resolvedTrace) -ne '.utrace' -or $resolvedTrace -match '["\r\n]') { throw 'Expected an existing .utrace with a safe literal path.' }
$traceItem=Get-Item -LiteralPath $resolvedTrace
if ($traceItem.Length -le 0) { throw 'Trace is empty.' }
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$ownedBase=[IO.Path]::GetFullPath((Join-Path $workspace 'Saved/Verification/human_profile_analysis_20261001/insights_exports'))
$exportDirectory=[IO.Path]::GetFullPath((Join-Path $ownedBase ((Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+$Label)))
if (-not $exportDirectory.StartsWith($ownedBase+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Export directory escaped its owned output root.' }
if (Test-Path -LiteralPath $exportDirectory) { throw 'Export directory already exists; preserve it and choose a fresh label.' }
New-Item -ItemType Directory -Path $exportDirectory -Force | Out-Null
$responsePath=Join-Path $exportDirectory 'commands.txt'
$startValue=$StartSeconds.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
$endValue=$EndSeconds.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
$commandLines=@(
    ('TimingInsights.ExportThreads "'+(Join-Path $exportDirectory 'threads.csv')+'"'),
    ('TimingInsights.ExportTimers "'+(Join-Path $exportDirectory 'timers.csv')+'"'),
    ('TimingInsights.ExportTimingEvents "'+(Join-Path $exportDirectory 'game_render_events.csv')+'" -threads="GameThread,Render*,RHIThread" -columns="ThreadId,ThreadName,TimerId,TimerName,StartTime,EndTime,Duration,Depth" -startTime='+$startValue+' -endTime='+$endValue)
)
$commandLines | Set-Content -LiteralPath $responsePath -Encoding utf8
$insightsPath='C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealInsights.exe'
if (-not (Test-Path -LiteralPath $insightsPath -PathType Leaf)) { throw 'Installed Unreal Insights executable missing.' }
$logPath=Join-Path $exportDirectory 'insights.log'
$arguments=@(
    ('-OpenTraceFile="'+$resolvedTrace+'"'),
    '-AutoQuit',
    '-NoUI',
    ('-ExecOnAnalysisCompleteCmd="@='+$responsePath+'"'),
    ('-ABSLOG="'+$logPath+'"')
)
$receipt=[ordered]@{
    prepared_utc=[DateTime]::UtcNow.ToString('o'); status='prepared_not_launched';
    trace_path=$resolvedTrace; trace_bytes=$traceItem.Length; trace_last_write_utc=$traceItem.LastWriteTimeUtc.ToString('o');
    source_trace_sha256=(Get-FileHash -LiteralPath $resolvedTrace -Algorithm SHA256).Hash;
    executable=$insightsPath; arguments=$arguments; export_directory=$exportDirectory; interval_start_s=$StartSeconds; interval_end_s=$EndSeconds;
    editor_calls=$false; tests_run=$false;
    note='AutoQuit occurs after analysis and response-file commands. Exit alone does not prove export succeeded; inspect log and all three CSV files. No tests are enabled.'
}
if ($Launch) {
    $process=Start-Process -FilePath $insightsPath -ArgumentList $arguments -WindowStyle Hidden -PassThru
    try { $process.PriorityClass='BelowNormal' } catch { $receipt.priority_warning=$_.Exception.Message }
    $receipt.status='launched'
    $receipt.pid=$process.Id
    $receipt.launch_utc=[DateTime]::UtcNow.ToString('o')
}
$receiptPath=Join-Path $exportDirectory 'receipt.json'
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
$receipt | ConvertTo-Json -Depth 6
