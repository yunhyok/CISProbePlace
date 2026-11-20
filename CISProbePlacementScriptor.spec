# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('openpyxl')


a = Analysis(
    ['cis_probe_placement_scriptor.py'],
    pathex=[],
    binaries=[],
    # The built-in help document is read from disk at run time.
    datas=[('cisprobeplace/help', 'cisprobeplace/help')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # openpyxl uses these only when they happen to be installed. Leaving them out
    # keeps the build the same on every machine, whatever else is installed there.
    excludes=['numpy', 'pandas', 'lxml', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CISProbePlacementScriptor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CISProbePlacementScriptor',
)
