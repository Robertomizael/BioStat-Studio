# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

project = Path(SPECPATH)

a = Analysis(
    [str(project / 'desktop_main.py')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / 'app' / 'static'), 'app/static')],
    hiddenimports=[
        'uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto','uvicorn.lifespan.on',
        'scipy.stats','pyreadstat','openpyxl','xlrd','webview',
        'webview.platforms.cocoa','webview.platforms.winforms'
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='BioStat Studio',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='BioStat Studio')

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='BioStat Studio.app',
        bundle_identifier='mx.biostatstudio.app',
        info_plist={
            'CFBundleName': 'BioStat Studio',
            'CFBundleDisplayName': 'BioStat Studio',
            'CFBundleShortVersionString': '0.3.0',
            'NSHighResolutionCapable': True,
        },
    )
