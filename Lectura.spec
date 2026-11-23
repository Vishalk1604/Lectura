# -*- mode: python ; coding: utf-8 -*-
# Build with:  build.bat   (or: .venv\Scripts\python.exe -m PyInstaller --noconfirm Lectura.spec)

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = [("assets/lectura.ico", "assets"), ("assets/lectura.png", "assets"),
         ("assets/chevron.png", "assets")]
datas += collect_data_files("pptx")       # default.pptx template
datas += collect_data_files("docx")       # default.docx template
datas += collect_data_files("reportlab")
binaries = collect_dynamic_libs("windows_capture")

a = Analysis(
    ["run_lectura.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["windows_capture", "win32api", "win32con"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PySide6.QtWebEngineCore",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Lectura",
    icon="assets/lectura.ico",
    console=False,
    upx=False,
    runtime_tmpdir=None,
    version=None,
)
