@echo off
rem Starts Lectura with the decision log turned on.
rem Each recording then writes debug.log next to its captures in
rem %LOCALAPPDATA%\Lectura\sessions\<date-time>\  (explains every saved or skipped page).
set LECTURA_DEBUG=1
cd /d "%~dp0"
if exist "%~dp0dist\Lectura.exe" (
    start "" "%~dp0dist\Lectura.exe"
) else (
    start "" "%~dp0.venv\Scripts\pythonw.exe" -m lectura
)
