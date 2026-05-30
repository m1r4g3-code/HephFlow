# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for HephFlow.

Build:  pyinstaller pressflow.spec
Output: dist/HephFlow.exe  (single file; the Whisper model is NOT bundled — it
        downloads to the HuggingFace cache on first run, or is reused if cached)

The speech stack ships native libraries that PyInstaller can't auto-detect, so
we collect_all() the tricky packages (CTranslate2, PyAV, onnxruntime, etc.).
"""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [("assets", "assets")]
binaries = []
hiddenimports = [
    "keyboard", "pyperclip", "pyautogui", "PIL", "numpy",
    # Local modules (imported lazily in a couple of places).
    "config", "recorder", "transcriber", "paster", "pill", "tray",
    "settings", "sounds", "enhance",
]

# Pull in everything (libs + data + submodules) for the native-heavy deps.
for _pkg in ("faster_whisper", "ctranslate2", "av", "onnxruntime",
             "tokenizers", "huggingface_hub", "hf_xet", "sounddevice"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HephFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX can corrupt the native DLLs; keep off.
    runtime_tmpdir=None,
    console=False,             # --noconsole (windowed). Set True to debug.
    disable_windowed_traceback=False,
    icon="assets/icon_idle.ico",
)
