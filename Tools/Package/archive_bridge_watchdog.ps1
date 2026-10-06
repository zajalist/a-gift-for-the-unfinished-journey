param(
    [Parameter(Mandatory = $true)][string]$ArchivePath,
    [int]$RawPid = 0,
    [int]$TunnelPid = 0
)

$ErrorActionPreference = 'Stop'
$archive = (Resolve-Path -LiteralPath $ArchivePath).Path
$python = (Get-Command python.exe).Source
$ssh = (Get-Command ssh.exe).Source
$rawScript = Join-Path $PSScriptRoot 'serve_range_file.py'
$key = Join-Path $env:USERPROFILE '.ssh\zajalist.pem'
$logDirectory = Split-Path -Parent $archive
$watchLog = Join-Path $logDirectory 'archive_bridge_watchdog.log'
$rawLog = Join-Path $logDirectory 'archive_bridge_raw.log'
$rawErrorLog = Join-Path $logDirectory 'archive_bridge_raw_error.log'
$tunnelLog = Join-Path $logDirectory 'archive_bridge_tunnel.log'
$tunnelErrorLog = Join-Path $logDirectory 'archive_bridge_tunnel_error.log'

function Is-Alive([int]$ProcessId) {
    return $ProcessId -gt 0 -and $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Record([string]$Message) {
    Add-Content -LiteralPath $watchLog -Value ("{0:o} {1}" -f (Get-Date), $Message)
}

Record "Watchdog started, adopting raw PID $RawPid and tunnel PID $TunnelPid"
while ($true) {
    if (-not (Is-Alive $RawPid)) {
        try {
            $process = Start-Process -FilePath $python -ArgumentList @(
                $rawScript, $archive, '--port', '8766'
            ) -WindowStyle Hidden -RedirectStandardOutput $rawLog -RedirectStandardError $rawErrorLog -PassThru
            $RawPid = $process.Id
            Record "Started raw server PID $RawPid"
        } catch {
            Record "Raw server start failed: $($_.Exception.Message)"
        }
    }
    if (-not (Is-Alive $TunnelPid)) {
        try {
            $process = Start-Process -FilePath $ssh -ArgumentList @(
                '-i', $key, '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                '-N', '-R', '127.0.0.1:8766:127.0.0.1:8766',
                'zajalist@srv-dev-01.tail599939.ts.net'
            ) -WindowStyle Hidden -RedirectStandardOutput $tunnelLog -RedirectStandardError $tunnelErrorLog -PassThru
            $TunnelPid = $process.Id
            Record "Started tunnel PID $TunnelPid"
        } catch {
            Record "Tunnel start failed: $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 10
}
