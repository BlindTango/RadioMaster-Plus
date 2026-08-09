# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

block_cipher = None

# When run via `pyinstaller packaging/radiomaster.spec`, cwd is the project root
project_root = os.getcwd()
src_dir = os.path.join(project_root, 'src')
resources_dir = os.path.join(project_root, 'resources')

a = Analysis(
    [os.path.join(src_dir, 'radiomaster', '__main__.py')],
    pathex=[src_dir],
    binaries=[],
    datas=[
        (resources_dir, 'resources'),
        (os.path.join(project_root, 'tools'), 'tools'),
        (os.path.join(src_dir, 'radiomaster', 'i18n', 'en'), 'radiomaster/i18n/en'),
    ],
    hiddenimports=[
        'wx',
        'requests',
        'httpx',
        'platformdirs',
        'mutagen',
        'feedparser',
        'apscheduler',
        'PIL',
        'Pillow',
        'lxml',
        'bs4',
        'win32com',
        'acoustid',
        'musicbrainzngs',
        'bleach',
        'Babel',
        'numpy',
        'av',
        'sounddevice',
        'comtypes',
        'comtypes.client',
        'radiomaster',
        'radiomaster.ui',
        'radiomaster.engine',
        'radiomaster.services',
        'radiomaster.database',
        'radiomaster.utils',
        'radiomaster.i18n',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
    ],
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
    # exclude_binaries=True is what makes this a genuine onedir build --
    # binaries/zipfiles/datas live only in the COLLECT step below,
    # alongside the exe in _internal/, instead of also being embedded
    # directly into the exe itself. Without this, the exe is capable of
    # self-extracting into a fresh %TEMP%\_MEI* folder on every launch
    # (PyInstaller's onefile mode) as a fallback -- which is exactly the
    # failure mode behind "Failed to load Python DLL
    # '...\_MEI######\python312.dll'" after an in-app update: if that
    # self-extraction is ever interrupted or blocked (AV scanning a fresh
    # %TEMP% extraction, a permissions hiccup, disk space, cleanup of a
    # previous _MEI folder racing a new one), the app fails to start with
    # this confusing error -- even though the actual install right next
    # to it in _internal/ is completely fine. This app's entire design
    # (get_paths()'s portable-mode detection, the in-app updater
    # overwriting files in place, the installer's per-file copy) already
    # assumes a stable onedir layout next to the exe; onefile-style self-
    # extraction to a new random temp directory every run was never an
    # intentional capability, just an unset flag.
    exclude_binaries=True,
    name='RadioMaster+',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(resources_dir, 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RadioMaster+',
)
