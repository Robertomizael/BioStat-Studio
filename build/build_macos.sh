#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-desktop.txt
.venv-build/bin/pyinstaller --clean --noconfirm biostat.spec
rm -f dist/BioStat_Studio_macOS.dmg
hdiutil create -volname "BioStat Studio" -srcfolder "dist/BioStat Studio.app" -ov -format UDZO dist/BioStat_Studio_macOS.dmg
