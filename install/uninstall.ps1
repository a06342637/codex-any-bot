param([switch]$Purge)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'codex-any-bot'))
$expected = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'codex-any-bot'))
if ($root -ne $expected -or -not $root.EndsWith('\codex-any-bot')) { throw 'Unexpected installation path' }
if (Test-Path -LiteralPath (Join-Path $root 'current.json')) {
    $current = Get-Content -LiteralPath (Join-Path $root 'current.json') -Raw | ConvertFrom-Json
    & $current.executable stop-local
    if ($LASTEXITCODE -ne 0) { throw 'Client has not stopped; retry before removing files.' }
}
$task = Get-ScheduledTask -TaskName 'codex-any-bot' -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName 'codex-any-bot' -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName 'codex-any-bot' -Confirm:$false
}
# Only stop executables under this exact application's directory.
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($Purge -and (Test-Path -LiteralPath $root)) {
    Remove-Item -LiteralPath $root -Recurse -Force
    Write-Host 'Uninstalled and removed this application data. Remove its device card in Telegram too.'
} else {
    Write-Host 'Autostart removed and client stopped. Config and versions retained. Use -Purge to remove them.'
}
