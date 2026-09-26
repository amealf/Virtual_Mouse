param([Parameter(Mandatory=$true)][string]$InnoCompiler)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & '.\.venv\Scripts\python.exe' -m pip install 'pyinstaller==6.22.0'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed' }
    & '.\.venv\Scripts\python.exe' -m PyInstaller GestureController.spec --distpath dist-v0.2.1
    if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
    & $InnoCompiler installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
} finally {
    Pop-Location
}
