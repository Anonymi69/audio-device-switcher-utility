@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  Audio Device Switcher - Build Script
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.10+ from https://python.org and re-run this script.
    pause
    exit /b 1
)

echo [1/5] Installing dependencies from requirements.txt ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. See output above.
    pause
    exit /b 1
)

echo.
echo [2/5] Cleaning previous build artifacts ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "Audio Device Switcher.spec" del /q "Audio Device Switcher.spec"
if exist main.spec del /q main.spec

echo.
echo [3/5] Checking for icon.ico ...
if not exist "icon.ico" (
    echo [WARN] icon.ico not found next to build.cmd — building without a custom icon.
    set "ICON_FLAG="
    set "ICON_DATA_FLAG="
) else (
    set "ICON_FLAG=--icon=icon.ico"
    set "ICON_DATA_FLAG=--add-data=icon.ico;."
)

echo.
echo [4/5] Building executable with PyInstaller ...
python -m PyInstaller --noconfirm --onefile --noconsole --name "Audio Device Switcher" %ICON_FLAG% %ICON_DATA_FLAG% main.py
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed. See output above.
    pause
    exit /b 1
)

echo.
echo [5/5] Finalizing output ...
if exist "dist\main.exe" (
    move /y "dist\main.exe" "dist\Audio Device Switcher.exe" >nul
)

if not exist "dist\Audio Device Switcher.exe" (
    echo [ERROR] Expected output "dist\Audio Device Switcher.exe" was not found.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Build complete: dist\Audio Device Switcher.exe
echo ============================================
echo.

start "" "%~dp0dist"

endlocal