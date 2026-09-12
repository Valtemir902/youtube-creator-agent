# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

ROOT = Path(SPECPATH)
SRC = ROOT / "src"

datas = []
binaries = []
hiddenimports = [
    "analista_metricas",
    "publicador_youtube",
    "tiktoken_ext.openai_public",
    "tiktoken_ext",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

datas += collect_data_files("googleapiclient")
for package in ("imageio", "imageio-ffmpeg", "tqdm", "moviepy"):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass

for package in ("whisper", "imageio_ffmpeg"):
    try:
        pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_bins
        hiddenimports += pkg_hidden
    except Exception:
        pass

# Do not manually mix Qt DLLs from other bindings. PyInstaller's PySide6 hook
# collects the matching Qt runtime, including QtWebEngineProcess, from the pinned
# release environment.
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="YouTube-Creator-Agent-Elite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
