param([string]$Server, [string]$Code, [switch]$Update, [string]$Version = 'v0.2.7', [switch]$NoAutoStart, [switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -Force
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Archive\Microsoft.PowerShell.Archive.psd1') -Force
    if (-not $NoAutoStart) { Import-Module (Join-Path $PSHOME 'Modules\ScheduledTasks\ScheduledTasks.psd1') -Force }
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = if ($env:ANYBOT_DATA_DIR) { $env:ANYBOT_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'codex-any-bot' }
$root = [IO.Path]::GetFullPath($root)
if ((Split-Path $root -Leaf) -ne 'codex-any-bot') { throw 'Installation directory must end in codex-any-bot.' }
if ((Test-Path -LiteralPath $root) -and ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Refusing a linked installation directory.' }
function Assert-AppPath([string]$Value) {
    $cursor = [IO.Path]::GetFullPath($Value)
    if (-not $cursor.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes the installation directory.' }
    while ($cursor -ne $root) {
        $entry = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Refusing a linked application path.' }
        $cursor = Split-Path $cursor -Parent
    }
}
foreach ($relative in @('ownership.json', 'config.json', 'current.json', 'previous.json', 'cache', 'versions')) { Assert-AppPath (Join-Path $root $relative) }
$marker = Join-Path $root 'ownership.json'
$ownership = @{ app = 'codex-any-bot'; schema = 1; autostart = $false }
if (Test-Path -LiteralPath $marker) {
    $ownership = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($ownership.app -ne 'codex-any-bot' -or $ownership.schema -ne 1 -or $ownership.autostart -isnot [bool]) { throw 'Directory belongs to another application or has an invalid ownership marker.' }
} elseif ((Test-Path -LiteralPath $root) -and @(Get-ChildItem -LiteralPath $root -Force).Count -gt 0) {
    if (-not $Update) { throw 'Non-empty directory has no ownership marker; refusing to claim its files.' }
    try {
        $legacyConfig = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
        $legacyPointer = Get-Content -LiteralPath (Join-Path $root 'current.json') -Raw | ConvertFrom-Json
        if ($legacyConfig.protocol -ne 1 -or $legacyConfig.token -notmatch '^[a-f0-9]{64}$' -or $legacyConfig.device_id -notmatch '^[a-f0-9]{16}$' -or $legacyConfig.server -notmatch '^https://') { throw 'Invalid legacy config' }
        $legacyExe = [IO.Path]::GetFullPath($legacyPointer.executable)
        Assert-AppPath $legacyExe
        if (-not $legacyExe.StartsWith($root + '\versions\', [StringComparison]::OrdinalIgnoreCase) -or (Split-Path $legacyExe -Leaf) -ne 'codex-any-bot.exe' -or -not (Test-Path -LiteralPath $legacyExe -PathType Leaf)) { throw 'Invalid legacy executable' }
        $ownership.autostart = $true
    } catch { throw 'Cannot verify ownership of this non-empty directory. Its files were not changed.' }
}
$taskName = 'codex-any-bot'
$repo = 'https://github.com/a06342637/codex-any-bot/releases'
if (-not $Update -and (Test-Path -LiteralPath (Join-Path $root 'config.json'))) { throw 'Already installed. Update from Telegram or run this installer with -Update.' }
if ($Version -notmatch '^v\d+\.\d+\.\d+$') { throw 'Invalid release version' }
$createdRoot = -not (Test-Path -LiteralPath $root)
New-Item -ItemType Directory -Path $root -Force | Out-Null
if (-not (Test-Path -LiteralPath $marker)) { $ownership | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding utf8 }
$cache = Join-Path $root 'cache'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
if ((Get-Item -LiteralPath $cache).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing a linked cache directory.' }
$staging = Join-Path $cache ('install-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
function Invoke-QuietClient([string[]]$ClientArgs) {
    $process = Start-Process -FilePath $consoleExe -ArgumentList ($ClientArgs -join ' ') -WindowStyle Hidden -Wait -PassThru
    return $process.ExitCode
}
try {
    if ($Update) {
        $latest = Invoke-RestMethod "$repo/latest/download/manifest.json"
        $Version = $latest.version
        if ($Version -notmatch '^v\d+\.\d+\.\d+$') { throw 'Invalid release version' }
    }
    $release = "$repo/download/$Version"
    $manifest = Invoke-RestMethod "$release/manifest.json"
    if ($manifest.version -ne $Version) { throw 'Manifest version mismatch' }
    $osArch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $asset = if ($osArch -eq 'ARM64') { 'codex-any-bot-windows-arm64.zip' } else { 'codex-any-bot-windows-x64.zip' }
    $expected = $manifest.files.$asset.sha256
    if ($expected -notmatch '^[a-f0-9]{64}$') { throw 'Missing archive checksum' }
    $archive = Join-Path $staging $asset
    Invoke-WebRequest "$release/$asset" -OutFile $archive -UseBasicParsing
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Archive checksum mismatch' }
    $installPath = Join-Path $root ('versions\' + $Version + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    Expand-Archive -LiteralPath $archive -DestinationPath $installPath
    $exe = Join-Path $installPath 'codex-any-bot.exe'
    $consoleExe = Join-Path $installPath 'codex-any-bot-console.exe'
    if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $consoleExe)) { throw 'Missing executable in package' }
    Copy-Item -LiteralPath (Join-Path $installPath 'uninstall.ps1') -Destination (Join-Path $root 'uninstall.ps1') -Force
    if ($Update) {
        if ((Invoke-QuietClient @('stop-local')) -ne 0) { throw 'The existing client has not stopped; retry later.' }
    } else {
        $clientArgs = @('setup', '--cwd', (Get-Location).Path)
        if ($Code) { $clientArgs = @('join', '--code', $Code, '--cwd', (Get-Location).Path) }
        if ($Server) { $clientArgs += @('--server', $Server) }
        & $consoleExe @clientArgs
        if ($LASTEXITCODE -ne 0) { throw 'Setup failed. Check the printed error before continuing.' }
    }
    $pointer = Join-Path $root 'current.json'
    if (Test-Path -LiteralPath $pointer) { Copy-Item -LiteralPath $pointer -Destination (Join-Path $root 'previous.json') -Force }
    if (-not $NoAutoStart) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
        $action = New-ScheduledTaskAction -Execute $exe -Argument 'run' -WorkingDirectory $root
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        $ownership.autostart = $true
    }
    $ownership | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $staging 'ownership.json') -Encoding utf8
    Move-Item -LiteralPath (Join-Path $staging 'ownership.json') -Destination $marker -Force
    @{ executable = $exe; console_executable = $consoleExe; version = $Version } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $staging 'current.json') -Encoding utf8
    Move-Item -LiteralPath (Join-Path $staging 'current.json') -Destination $pointer -Force
    Remove-Item -LiteralPath (Join-Path $root 'stop.request') -Force -ErrorAction SilentlyContinue
    if (-not $NoLaunch) {
        Start-Process -FilePath $exe -ArgumentList 'run' -WorkingDirectory $root -WindowStyle Hidden | Out-Null
        $online = Invoke-QuietClient @('wait-online', '--timeout', '20')
        if ($online -eq 0) { Write-Host 'Online in Telegram. Waiting for your commands.' }
        else { Write-Warning 'Installed, but online status is not confirmed yet. Check network and the log below.' }
    }
    Write-Host "Install directory: $root"
    Write-Host "Log: $root\agent.log"
    Write-Host "Config (private): $root\config.json"
    Write-Host "Status: & '$consoleExe' status"
    Write-Host ('Uninstall: powershell -NoProfile -ExecutionPolicy Bypass -File "' + $root + '\uninstall.ps1" -Purge')
} catch {
    Write-Warning "Installation did not finish. Log: $root\agent.log"
    if (Test-Path -LiteralPath (Join-Path $root 'uninstall.ps1')) {
        Write-Warning ('Cleanup: powershell -NoProfile -ExecutionPolicy Bypass -File "' + $root + '\uninstall.ps1" -Purge')
    } else { Write-Warning 'No working client was installed; a fresh download directory will be cleaned automatically.' }
    throw
} finally {
    $resolvedStage = [IO.Path]::GetFullPath($staging)
    if (-not $resolvedStage.StartsWith($root + '\cache\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected staging path' }
    if (Test-Path -LiteralPath $resolvedStage) {
        if ((Get-Item -LiteralPath $resolvedStage).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing linked staging path' }
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
    if ($createdRoot -and -not (Test-Path -LiteralPath (Join-Path $root 'uninstall.ps1')) -and -not (Test-Path -LiteralPath (Join-Path $root 'config.json'))) {
        if ((Get-Content -LiteralPath (Join-Path $root 'ownership.json') -Raw | ConvertFrom-Json).app -ne 'codex-any-bot') { throw 'Unexpected cleanup owner' }
        if ([IO.Path]::GetFullPath($root) -ne $root -or (((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw 'Unexpected cleanup target' }
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
