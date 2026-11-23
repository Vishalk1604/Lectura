@echo off
rem Builds dist\Lectura.exe (single file). Run from anywhere.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    py -3.12 -m venv .venv || exit /b 1
    .venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
    .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)
if not exist assets\lectura.ico .venv\Scripts\python.exe tools\make_icon.py
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean Lectura.spec || exit /b 1
echo.
echo Built dist\Lectura.exe
