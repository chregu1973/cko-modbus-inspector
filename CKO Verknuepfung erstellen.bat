@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut((Join-Path (Get-Location) 'CKO Modbus Inspector.lnk')); $shortcut.TargetPath = (Join-Path (Get-Location) 'CKO Modbus Inspector starten.bat'); $shortcut.WorkingDirectory = (Get-Location).Path; $shortcut.IconLocation = (Join-Path (Get-Location) 'cko_logo.ico') + ',0'; $shortcut.Description = 'CKO Modbus Inspector starten'; $shortcut.Save()"
if errorlevel 1 (
  echo Die CKO-Verknuepfung konnte nicht erstellt werden.
  if /I not "%~1"=="/quiet" pause
  exit /b 1
)
if /I not "%~1"=="/quiet" (
  echo CKO Modbus Inspector.lnk wurde erstellt.
  echo Die Verknuepfung zeigt das CKO-Logo und kann auch auf den Desktop kopiert werden.
  pause
)
exit /b 0
