@echo off
rem Rhino Open AI Kit - start the local model server (Windows)
rem Double-click to start. Close the window to stop.
setlocal enabledelayedexpansion
set "KIT=%~dp0"
set "KIT=%KIT:~0,-1%"

rem Load settings
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%KIT%\kit.conf") do set "%%a=%%b"

if not defined NGL set "NGL=99"

rem Find llama-server.exe anywhere under bin\win
set "SERVER="
for /r "%KIT%\bin\win" %%f in (llama-server.exe) do if exist "%%f" if not defined SERVER set "SERVER=%%f"
if not defined SERVER (
  echo llama-server.exe not found. Run setup-win.bat first.
  pause & exit /b 1
)

if not exist "%KIT%\models\%MODEL%" (
  echo Model not found: models\%MODEL%  (run setup-win.bat to download it)
  pause & exit /b 1
)

set "EXTRA="
if defined MMPROJ if exist "%KIT%\models\%MMPROJ%" set "EXTRA=--mmproj "%KIT%\models\%MMPROJ%""

echo Starting %MODEL% on http://127.0.0.1:%PORT%  (close window to stop)
"%SERVER%" -m "%KIT%\models\%MODEL%" -c %CTX% --port %PORT% --host 127.0.0.1 -ngl %NGL% --jinja !EXTRA!
pause
