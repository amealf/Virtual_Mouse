@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Project environment was not found: %PYTHON_EXE%
    echo Create the .venv environment and install requirements before running this launcher.
    pause
    exit /b 1
)

"%PYTHON_EXE%" "%APP_DIR%main.py" %*
