param([switch]$Purge, [switch]$KeepData)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -Force
    Import-Module (Join-Path $PSHOME 'Modules\CimCmdlets\CimCmdlets.psd1') -Force
}
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$expected = if ($env:ANYBOT_DATA_DIR) { [IO.Path]::GetFullPath($env:ANYBOT_DATA_DIR) } else { [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'codex-any-bot')) }
if ($root -ne $expected -or (Split-Path $root -Leaf) -ne 'codex-any-bot') { throw 'Unexpected installation path. Run the installed uninstaller.' }
if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing a linked installation directory.' }
$marker = Join-Path $root 'ownership.json'
if (-not (Test-Path -LiteralPath $marker)) { throw 'Ownership marker missing. Update the client before using this uninstaller.' }
$ownership = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($ownership.app -ne 'codex-any-bot') { throw 'Invalid ownership marker' }
$helper = $null
$pointer = Join-Path $root 'current.json'
if (Test-Path -LiteralPath $pointer) {
    $current = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
    $helper = $current.console_executable
}
if (-not $helper -or -not (Test-Path -LiteralPath $helper)) {
    $candidate = Get-ChildItem -LiteralPath (Join-Path $root 'versions') -Filter 'codex-any-bot-console.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $helper = $candidate.FullName }
}
if ($helper) {
    $helper = [IO.Path]::GetFullPath($helper)
    if (-not $helper.StartsWith($root + '\versions\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected helper path' }
    & $helper stop-local
    if ($LASTEXITCODE -ne 0) { throw 'Client has not stopped. Wait for any update to finish, then retry.' }
}
if ($ownership.autostart) {
    if ($PSVersionTable.PSEdition -eq 'Desktop') { Import-Module (Join-Path $PSHOME 'Modules\ScheduledTasks\ScheduledTasks.psd1') -Force }
    $task = Get-ScheduledTask -TaskName 'codex-any-bot' -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName 'codex-any-bot' -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName 'codex-any-bot' -Confirm:$false
    }
}
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($KeepData) {
    Write-Host "Stopped and removed autostart. Data retained at $root"
    exit 0
}
$cloudPending = $false
$cachePending = $false
if ($helper) {
    & $helper forget
    $cloudPending = $LASTEXITCODE -ne 0
    & $helper clean-cache
    $cachePending = $LASTEXITCODE -ne 0
} elseif (Test-Path -LiteralPath (Join-Path $root 'config.json')) {
    $cloudPending = $true
    Write-Warning 'Client helper missing; remove the device binding in Telegram.'
}
if ([IO.Path]::GetFullPath($root) -ne $expected -or (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).app -ne 'codex-any-bot') { throw 'Refusing unexpected cleanup target' }
Set-Location -LiteralPath ([IO.Path]::GetTempPath())
Remove-Item -LiteralPath $root -Recurse -Force
Write-Host 'Local client, versions, configuration, logs, cache and autostart removed.'
if ($cloudPending) { Write-Warning 'Cloud binding could not be removed. Use Telegram > Machine settings > Remove device.' }
if ($cachePending) { Write-Warning 'Some identified legacy temporary files could not be removed; see the paths printed above.' }
