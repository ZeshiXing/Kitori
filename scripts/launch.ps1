param([ValidateSet('local')][string]$Mode = 'local', [switch]$NoBrowser,
      [ValidateSet('overlay','luna','both')][string]$Display = 'overlay')
$ErrorActionPreference = 'Stop'
$taskCaptionRoot = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $taskCaptionRoot 'logs') | Out-Null
$taskCaptionPython = Join-Path $taskCaptionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskCaptionPython)) {
    throw 'Project environment missing. Create .venv and run: .venv\Scripts\python.exe -m pip install -e .'
}
# GUI restarts use Windows PowerShell 5.1, whose default file encoding is ANSI.
# Validate UTF-8 config before stopping an otherwise working caption runtime.
$taskConfig = Get-Content -LiteralPath (Join-Path $taskCaptionRoot 'config\caption.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskPreflight = Join-Path $PSScriptRoot 'check_local_runtime.py'
if (Test-Path -LiteralPath $taskPreflight) {
    & $taskCaptionPython $taskPreflight --mode $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Local model preparation is incomplete; current captions were kept running.' }
}
& (Join-Path $PSScriptRoot 'stop.ps1') -KeepSettings
$taskLunaDir = Join-Path $taskCaptionRoot 'apps\LunaTranslator\LunaTranslator_x64'
$taskLunaExe = Join-Path $taskLunaDir 'LunaTranslator.exe'
$taskExistingLuna = Get-CimInstance Win32_Process -Filter "Name='LunaTranslator.exe'" |
    Where-Object { $_.ExecutablePath -ieq $taskLunaExe }
$taskConfig | Add-Member -NotePropertyName display_mode -NotePropertyValue $Display -Force
$taskConfig.luna_output_enabled = $Display -in @('luna','both')
[IO.File]::WriteAllText((Join-Path $taskCaptionRoot 'config\caption.json'), ($taskConfig | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
if ($taskConfig.luna_output_enabled) {
    & $taskCaptionPython (Join-Path $PSScriptRoot 'configure_luna.py') --check
    if ($LASTEXITCODE -eq 3) {
        # Only this project's portable instance is restarted for user-HTML changes.
        foreach ($taskLunaProcess in $taskExistingLuna) {
            Stop-Process -Id $taskLunaProcess.ProcessId -ErrorAction Stop
        }
        $taskExistingLuna = $null
        & $taskCaptionPython (Join-Path $PSScriptRoot 'configure_luna.py')
        if ($LASTEXITCODE -ne 0) { throw 'Luna extension setup failed.' }
    } elseif ($LASTEXITCODE -ne 0) { throw 'Luna extension check failed.' }
    if (-not $taskExistingLuna) {
        # This is the user-requested interactive subtitle window.
        Start-Process -FilePath $taskLunaExe -WorkingDirectory $taskLunaDir -WindowStyle Normal
    }
}
$env:JP_CAPTION_ROOT = $taskCaptionRoot
$env:PYTHONIOENCODING = 'utf-8'
& $taskCaptionPython (Join-Path $PSScriptRoot 'prepare_runtime.py') --mode $Mode
if ($LASTEXITCODE -ne 0) { throw 'Caption preparation failed. See logs/plugin-host-check.log.' }
$taskRunner = Join-Path $PSScriptRoot 'run_backend.py'
Start-Process -FilePath $taskCaptionPython -ArgumentList @($taskRunner) `
    -WorkingDirectory $taskCaptionRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $taskCaptionRoot 'logs\controller.stdout.log') `
    -RedirectStandardError (Join-Path $taskCaptionRoot 'logs\controller.stderr.log')
Write-Output "Captions started ($Mode). Model and runtime readiness are reported in settings."
Write-Output "Status: $taskCaptionRoot\logs\status.json"
Write-Output "Subtitle output: $Display (desktop, no browser tab required)"

