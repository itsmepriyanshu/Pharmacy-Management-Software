$ErrorActionPreference = 'Stop'

if (-not (Test-Path '.venv\Scripts\pyinstaller.exe')) {
    Write-Error 'Create .venv and install requirements.txt before building.'
}

.\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --windowed `
    --name DipeshMedicalHall `
    --onedir `
    --collect-all PySide6 `
    --collect-all pyqtgraph `
    main.py

if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed.'
}
Write-Host 'Build complete: dist\DipeshMedicalHall'
