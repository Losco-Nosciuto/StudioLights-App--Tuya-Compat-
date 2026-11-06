@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

if not exist ".venv\Scripts\python.exe" (
    echo [Studio Lights] Creo l'ambiente virtuale...
    python -m venv .venv
    if errorlevel 1 goto :error
    set "PYTHON=.venv\Scripts\python.exe"
    echo [Studio Lights] Installo le dipendenze...
    "!PYTHON!" -m pip install --upgrade pip --quiet
    "!PYTHON!" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

rem pythonw = nessuna finestra console. Gli errori finiscono in logs\studiolights.log
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" main.py
) else (
    "!PYTHON!" main.py
)
exit /b 0

:error
echo.
echo [Studio Lights] Installazione non riuscita. Controlla Python 3.12+ e la connessione.
pause
exit /b 1
