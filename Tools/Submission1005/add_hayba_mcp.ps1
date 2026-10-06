# Adds the Hayba MCP server to the Claude desktop app config (merges; keeps everything else).
$path = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
if (Test-Path $path) {
    Copy-Item $path "$path.bak" -Force
    $raw = Get-Content $path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) { $cfg = [pscustomobject]@{} } else { $cfg = $raw | ConvertFrom-Json }
} else { $cfg = [pscustomobject]@{} }
if (-not $cfg.PSObject.Properties["mcpServers"]) { $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) }
$hayba = [pscustomobject]@{
    command = "cmd"
    args    = @("/c", "cd /d D:\UnrealEngine\saskartarad && node D:\Hackathons\hayba\mcp-tools\hayba-mcp\dist\bootstrap.js")
    env     = [pscustomobject]@{
        UE_TCP_PORT = "52342"
        HAYBA_SETTINGS_PATH = "D:\UnrealEngine\saskartarad\Saved\HaybaMCP\settings.json"
        HAYBA_TOOL_INDEX_DIR = "D:\UnrealEngine\saskartarad\Saved\HaybaMCP"
    }
}
$cfg.mcpServers | Add-Member -NotePropertyName hayba -NotePropertyValue $hayba -Force
$cfg | ConvertTo-Json -Depth 20 | Set-Content -Path $path -Encoding UTF8
Write-Host "Hayba added to $path (backup: $path.bak). Now quit Claude from the tray and reopen it."
