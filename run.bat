@echo off
cd /d "%~dp0"
echo Starting FloorPlan3D server...
echo.

:: Try Windows Python launcher first
py app.py
if %ERRORLEVEL% EQU 0 goto end

:: Fallback directly to installed Python executable
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" app.py
if %ERRORLEVEL% EQU 0 goto end

echo.
echo Failed to start server. Please ensure Python is installed.
pause

:end
