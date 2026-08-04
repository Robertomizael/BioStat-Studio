$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --upgrade pip
.\.venv-build\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv-build\Scripts\pyinstaller.exe --clean --noconfirm biostat.spec
Compress-Archive -Path "dist\BioStat Studio\*" -DestinationPath "dist\BioStat_Studio_Windows_Portable.zip" -Force
