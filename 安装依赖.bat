@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_VERSION=3.12.10"
set "PY_TAG=312"
set "PY_DIR=%~dp0runtime\python"
set "PY_EXE=%PY_DIR%\python.exe"
set "DOWNLOAD_DIR=%~dp0runtime\downloads"
set "PY_ZIP=%DOWNLOAD_DIR%\python-%PY_VERSION%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-embed-amd64.zip"
set "GET_PIP=%DOWNLOAD_DIR%\get-pip.py"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"

echo ============================================
echo   MoistCanvas - installer
echo ============================================
echo.
echo This will download portable Python and install dependencies.
echo First run requires internet access.
echo.

if exist "%PY_EXE%" (
    echo [OK] Portable Python already installed:
    echo      %PY_EXE%
    echo Skipping Python download.
) else (
    echo [1/4] Preparing folders...
    if not exist "%PY_DIR%" mkdir "%PY_DIR%"
    if not exist "%DOWNLOAD_DIR%" mkdir "%DOWNLOAD_DIR%"

    echo.
    echo [2/4] Downloading portable Python %PY_VERSION%...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%' -UseBasicParsing } catch { Write-Host $_; exit 1 }"
    if errorlevel 1 (
        echo.
        echo [ERROR] Python download failed. Check your network and try again.
        pause
        exit /b 1
    )

    echo.
    echo [3/4] Extracting Python...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -LiteralPath '%PY_ZIP%' -DestinationPath '%PY_DIR%' -Force } catch { Write-Host $_; exit 1 }"
    if errorlevel 1 (
        echo.
        echo [ERROR] Python extraction failed.
        pause
        exit /b 1
    )

    echo.
    echo [4/4] Enabling site-packages...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$pth = Join-Path '%PY_DIR%' 'python%PY_TAG%._pth'; if (Test-Path $pth) { (Get-Content -LiteralPath $pth) -replace '^#import site$', 'import site' | Set-Content -LiteralPath $pth -Encoding ASCII } else { Write-Host 'Missing python._pth file'; exit 1 }"
    if errorlevel 1 (
        echo.
        echo [ERROR] Python configuration failed.
        pause
        exit /b 1
    )
)

echo.
echo [deps] Downloading get-pip.py...
if not exist "%DOWNLOAD_DIR%" mkdir "%DOWNLOAD_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%GET_PIP%' -UseBasicParsing } catch { Write-Host $_; exit 1 }"
if errorlevel 1 (
    echo.
    echo [ERROR] get-pip.py download failed. Check your network and try again.
    pause
    exit /b 1
)

echo.
echo [deps] Installing pip...
"%PY_EXE%" "%GET_PIP%" --no-warn-script-location
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

echo.
echo [deps] Upgrading pip...
"%PY_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo [ERROR] pip upgrade failed.
    pause
    exit /b 1
)

echo.
echo [deps] Installing Python packages from requirements.txt...
"%PY_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed. Check your network and try again.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Install complete
echo ============================================
echo You can now run the start script to launch MoistCanvas.
echo.
pause
endlocal
