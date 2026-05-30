@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_EXE=%~dp0runtime\python\python.exe"

echo ============================================
echo   MoistCanvas - run
echo ============================================
echo.

if not exist "%PY_EXE%" (
    echo [ERROR] Portable Python was not found at:
    echo     %PY_EXE%
    echo Please run the installer script first, then try again.
    echo.
    pause
    exit /b 1
)

if not exist "static\index.html" (
    echo [ERROR] static\index.html was not found.
    echo Make sure you are running this from the extracted MoistCanvas folder.
    echo.
    pause
    exit /b 1
)

if not exist "main.py" (
    echo [ERROR] main.py was not found in this folder.
    echo.
    pause
    exit /b 1
)

echo Starting MoistCanvas server...
echo URL: http://127.0.0.1:6767/
echo Close this window to stop the server.
echo.

start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:6767/"
"%PY_EXE%" main.py

echo.
echo Server stopped.
pause
endlocal
