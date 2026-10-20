param([switch]$KeepSettings)
$ErrorActionPreference = 'Stop'
$taskCaptionRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$taskCaptionScripts = @('run_backend.py','native_overlay.py','session_tray.py','recovery_monitor.py','reazon_worker.py')
if (-not $KeepSettings) { $taskCaptionScripts += 'caption_settings.py' }
$taskExpectedBackend = Join-Path $taskCaptionRoot 'apps\TigerBackend\audioWhisper\audioWhisper.exe'
$taskVenvPrefix = Join-Path $taskCaptionRoot '.venv\Scripts\python'
function Test-CaptionProcess($taskProcess) {
    if ($taskProcess.ExecutablePath -ieq $taskExpectedBackend) { return $true }
    if ($taskProcess.ExecutablePath -ieq (Join-Path $taskCaptionRoot 'apps\WindowsCaptionReader\WindowsCaptionReader.exe')) { return $true }
    $taskWindowsCaptionPrefix = (Join-Path $taskCaptionRoot 'apps\WindowsCaptionReader\')
    if ($taskProcess.Name -eq 'WindowsCaptionReader.exe' -and
        [string]$taskProcess.ExecutablePath -like "$taskWindowsCaptionPrefix*") { return $true }
    $taskNativePrefix = Join-Path $taskCaptionRoot 'apps\audio.cpp\'
    if ($taskProcess.Name -eq 'audiocpp_server.exe' -and
        [string]$taskProcess.ExecutablePath -like "$taskNativePrefix*") { return $true }
    if ($taskProcess.Name -notin @('python.exe','pythonw.exe')) { return $false }
    $taskCommand = [string]$taskProcess.CommandLine
    foreach ($taskScript in $taskCaptionScripts) {
        $taskAbsoluteScript = Join-Path $PSScriptRoot $taskScript
        if ($taskCommand -match ('(?i)(?:^|[\s"])' + [regex]::Escape($taskAbsoluteScript) + '(?:[\s"]|$)')) { return $true }
        # Also match the real child of this project's venv redirector when
        # Settings.cmd or a terminal used a relative script argument.
        if ($taskCommand -like "*$taskVenvPrefix*" -and
            $taskCommand -match ('(?i)(?:^|[\s"])(?:\.\\)?scripts[\\/]' + [regex]::Escape($taskScript) + '(?:[\s"]|$)')) { return $true }
    }
    return $false
}
# Paths are checked directly so stale PIDs and orphan Qt children are covered.
$taskProcesses = @(Get-CimInstance Win32_Process)
$taskTargets = @($taskProcesses | Where-Object { Test-CaptionProcess $_ })
$taskIds = @{}
foreach ($taskProcess in $taskTargets) { $taskIds[[int]$taskProcess.ProcessId] = $true }
# Include codecs and download workers owned by this runtime. The stop helper
# must survive when it was itself launched by a settings process being closed.
do {
    $taskAdded = $false
    foreach ($taskProcess in $taskProcesses) {
        if ($KeepSettings -and [string]$taskProcess.CommandLine -match '(?i)caption_settings\.py(?:[\s"]|$)') { continue }
        if ($taskProcess.ProcessId -ne $PID -and -not $taskIds.ContainsKey([int]$taskProcess.ProcessId) -and
            $taskIds.ContainsKey([int]$taskProcess.ParentProcessId)) {
            $taskIds[[int]$taskProcess.ProcessId] = $true
            $taskAdded = $true
        }
    }
} while ($taskAdded)
foreach ($taskProcess in ($taskProcesses | Where-Object { $taskIds.ContainsKey([int]$_.ProcessId) })) {
    $taskCurrent = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProcess.ProcessId)"
    if ($taskCurrent -and $taskCurrent.CreationDate -eq $taskProcess.CreationDate) {
        Stop-Process -Id $taskCurrent.ProcessId -ErrorAction SilentlyContinue
    }
}
$taskStopped = @{ stage = 'stopped'; backend = 'none'; updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
[void][IO.Directory]::CreateDirectory((Join-Path $taskCaptionRoot 'logs'))
[IO.File]::WriteAllText((Join-Path $taskCaptionRoot 'logs\status.json'), ($taskStopped | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
Write-Output 'Caption application stopped.'
