param([string]$Server, [string]$Code, [switch]$Update, [string]$Version = 'v0.1.0')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Join-Path $env:LOCALAPPDATA 'codex-any-bot'
$taskName = 'codex-any-bot'
$repo = 'https://github.com/a06342637/codex-any-bot/releases'
if ($Version -notmatch '^v\d+\.\d+\.\d+$') { throw 'Invalid release version' }
if (-not $Update -and (Test-Path -LiteralPath (Join-Path $root 'config.json'))) { throw 'Already installed. Use -Update or uninstall first.' }
if (-not $Update -and (-not $Server -or -not $Code)) { throw 'Server and Code are required.' }
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
$staging = Join-Path $env:TEMP ('codex-any-bot-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
$archive = Join-Path $staging $asset
Invoke-WebRequest "$release/$asset" -OutFile $archive -UseBasicParsing
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Archive checksum mismatch' }
$installPath = Join-Path $root ('versions\' + $Version + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $installPath -Force | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $installPath
$exe = Join-Path $installPath 'codex-any-bot.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Missing client executable' }
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'Client cannot run on this computer' }
if ($Update) {
    & $exe stop-local
    if ($LASTEXITCODE -ne 0) { throw 'The existing client has not stopped; update cancelled.' }
}
if (-not $Update) {
    & $exe join --server $Server --code $Code --cwd (Get-Location).Path
    if ($LASTEXITCODE -ne 0) { throw 'Pairing failed; no startup task installed' }
}
# Keep the previous version directory and pointer for rollback.
$pointer = Join-Path $root 'current.json'
if (Test-Path -LiteralPath $pointer) { Copy-Item -LiteralPath $pointer -Destination (Join-Path $root 'previous.json') -Force }
@{ executable = $exe; version = $Version } | ConvertTo-Json | Set-Content -LiteralPath $pointer -Encoding utf8
Copy-Item -LiteralPath (Join-Path $installPath 'uninstall.ps1') -Destination (Join-Path $root 'uninstall.ps1') -Force
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$action = New-ScheduledTaskAction -Execute $exe -Argument 'run' -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Remove-Item -LiteralPath (Join-Path $root 'stop.request') -Force -ErrorAction SilentlyContinue
# A detached process is used for the immediate start. The executable is built without a console.
Start-Process -FilePath $exe -ArgumentList 'run' -WorkingDirectory $root -WindowStyle Hidden | Out-Null
Write-Host 'Installed. The client runs in the background and starts when you sign in.'
Write-Host "Status: & '$exe' status"
Write-Host "Uninstall: powershell -NoProfile -ExecutionPolicy Bypass -File `"$root\uninstall.ps1`""
