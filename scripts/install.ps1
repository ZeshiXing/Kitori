param(
    [ValidateSet('auto','gpu','cpu','windows')][string]$Mode='auto',
    [ValidateSet('zh','en','ja')][string]$Language='zh',
    [switch]$WithLuna,
    [string]$CacheDirectory=''
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
function Get-SetupHash([string]$Path) {
    $taskHash=[Security.Cryptography.SHA256]::Create()
    $taskHashStream=[IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($taskHash.ComputeHash($taskHashStream))).Replace('-','').ToLowerInvariant() }
    finally { $taskHashStream.Dispose(); $taskHash.Dispose() }
}
$taskSetupRoot=Split-Path -Parent $PSScriptRoot
$taskSetupLock=$null
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    $taskSetupLock=[IO.File]::Open((Join-Path $taskSetupRoot '.install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    if ($Mode -eq 'auto') {
        $Mode='cpu'
        if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) { $Mode='gpu' }
    }
    $taskResources=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'setup_resources.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskBootstrap=Join-Path $taskSetupRoot 'apps\bootstrap'
    New-Item -ItemType Directory -Force -Path $taskBootstrap | Out-Null
    $taskUvArchive=Join-Path $taskBootstrap 'uv.zip'
    $taskUv=Join-Path $taskBootstrap 'uv.exe'
    Write-Output 'Preparing the private Python runtime...'
    if (-not (Test-Path -LiteralPath $taskUvArchive) -or
        (Get-SetupHash $taskUvArchive) -ine $taskResources.uv.sha256) {
        $taskPartial=$taskUvArchive+'.part'
        $taskClient=New-Object Net.WebClient
        [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
        try { $taskClient.DownloadFile($taskResources.uv.urls[0],$taskPartial) } finally { $taskClient.Dispose() }
        if ((Get-SetupHash $taskPartial) -ine $taskResources.uv.sha256) {
            throw 'uv download checksum mismatch. Run setup again.'
        }
        Move-Item -LiteralPath $taskPartial -Destination $taskUvArchive -Force
    }
    # A small, pinned upstream archive; never run a remotely fetched script.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $taskUvZip=[IO.Compression.ZipFile]::OpenRead($taskUvArchive)
    try {
        foreach($taskUvMember in $taskUvZip.Entries) {
            $taskMemberPath=[IO.Path]::GetFullPath((Join-Path $taskBootstrap $taskUvMember.FullName))
            if (-not $taskMemberPath.StartsWith($taskBootstrap+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe uv archive path.' }
            if ($taskUvMember.FullName.EndsWith('/')) { [IO.Directory]::CreateDirectory($taskMemberPath) | Out-Null }
            else { [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskMemberPath)) | Out-Null; [IO.Compression.ZipFileExtensions]::ExtractToFile($taskUvMember,$taskMemberPath,$true) }
        }
    } finally { $taskUvZip.Dispose() }
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $taskSetupRoot 'apps\python'
    $env:UV_CACHE_DIR=Join-Path $taskSetupRoot 'downloads\uv-cache'
    $env:UV_PYTHON_INSTALL_REGISTRY='0'
    $env:UV_PYTHON_INSTALL_BIN='0'
    $env:UV_NO_CONFIG='1'
    $env:UV_LINK_MODE='copy'
    $env:PYTHONIOENCODING='utf-8'
    $env:PYTHONNOUSERSITE='1'
    $taskPython=Join-Path $taskSetupRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) {
        & $taskUv venv --no-project --managed-python --python $taskResources.python --seed (Join-Path $taskSetupRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the private Python environment.' }
    }
    & $taskUv pip install --python $taskPython -r (Join-Path $taskSetupRoot 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency download/install failed. Run setup again to retry.' }
    & $taskUv pip install --python $taskPython --no-deps --editable $taskSetupRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the caption package.' }
    $taskArguments=@((Join-Path $PSScriptRoot 'setup_runtime.py'),'--mode',$Mode,'--language',$Language)
    if ($WithLuna) { $taskArguments+='--with-luna' }
    if ($CacheDirectory) { $taskArguments+=@('--cache-dir',$CacheDirectory) }
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed. Run setup again to resume.' }
    Write-Output 'Installation complete. Open Settings.cmd to choose recognition and display options.'
} catch {
    Write-Output ('ERROR: '+$_.Exception.Message)
    exit 1
} finally {
    if ($taskSetupLock) { $taskSetupLock.Dispose() }
}
