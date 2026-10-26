@echo off
setlocal
cd /d "%~dp0"

echo Starting FloorPlan3D...
echo.

set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%PROJECT_PYTHON%" goto run_app

set "PROJECT_PYTHON="
for %%V in (314 313 312 311) do (
    if not defined PROJECT_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PROJECT_PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)

if not defined PROJECT_PYTHON (
    echo Could not find Python 3.11 or newer.
    echo Install Python, then create a .venv and install requirements.txt.
    pause
    exit /b 1
)

:run_app
echo Using: %PROJECT_PYTHON%
"%PROJECT_PYTHON%" app.py
if errorlevel 1 (
    echo.
    echo FloorPlan3D stopped with an error. If a Python package is missing, install the project dependencies:
    echo   "%PROJECT_PYTHON%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

endlocal
