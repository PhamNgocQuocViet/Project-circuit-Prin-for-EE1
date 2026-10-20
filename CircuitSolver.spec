# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

datas = [
    ("LICENSE", "."),
    ("README.md", "."),
    ("ui/styles/*.qss", "ui/styles"),
    ("ui/vendor/katex/*", "ui/vendor/katex"),
    ("circuit_exports/*", "Circuit_exports"),
]

hiddenimports = [
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebEngineCore",
    "keyring",
    "keyring.backends.Windows",
    "win32ctypes.pywin32",
    "win32ctypes.pywin32.win32cred",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CircuitSolver",
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CircuitSolver",
)
