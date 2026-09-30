@echo off
setlocal
cd /d "%~dp0"
title CKO Modbus Inspector
color 09
cls
echo.
echo        C K O
echo   ==================
echo     MODBUS INSPECTOR
echo   CODE. HOST. DEPLOY.
echo   ==================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 wurde nicht gefunden.
  echo Bitte Python von https://www.python.org/downloads/ installieren.
  echo Dabei "Add Python to PATH" aktivieren.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Lokale Python-Umgebung wird eingerichtet ...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

if not exist "CKO Modbus Inspector.lnk" (
  call "CKO Verknuepfung erstellen.bat" /quiet
  if exist "CKO Modbus Inspector.lnk" echo CKO-Verknuepfung mit Logo wurde im Programmordner erstellt.
)

call ".venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :error

echo.
echo CKO Modbus Inspector startet auf http://127.0.0.1:48722
echo Zum Beenden dieses Fenster schliessen oder Strg+C druecken.
python app.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Die Installation oder der Start ist fehlgeschlagen.
pause
exit /b 1
