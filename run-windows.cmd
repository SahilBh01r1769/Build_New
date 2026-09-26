@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 or newer with the Windows py launcher is required.
    goto fail
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating First Run's local Python environment...
    py -3 -m venv ".venv"
    if errorlevel 1 goto fail
)

if not exist ".venv\.first-run-installed" (
    echo Installing First Run and its desktop dependency...
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 goto fail
    echo installed>".venv\.first-run-installed"
)

echo Opening First Run...
".venv\Scripts\python.exe" -m first_run.app
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo First Run could not start. The error is shown above.
pause
exit /b 1
