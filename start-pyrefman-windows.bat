@echo off
setlocal

:retry
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo PyRefMan failed to start. A retry may help if setup was interrupted by a brief internet issue.
    choice /C RE /N /M "Press R to retry or E to exit: "
    if errorlevel 2 exit /b %EXIT_CODE%
    echo.
    goto retry
)

exit /b %EXIT_CODE%
