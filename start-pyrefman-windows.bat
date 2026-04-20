@echo off
setlocal

set "POWERSHELL_EXE="
set "LAUNCH_SCRIPT=%~dp0scripts\start_windows.ps1"

for %%I in (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
    "%ProgramFiles%\PowerShell\7\pwsh.exe"
    "%ProgramFiles%\PowerShell\6\pwsh.exe"
) do if not defined POWERSHELL_EXE if exist "%%~I" set "POWERSHELL_EXE=%%~I"

if not defined POWERSHELL_EXE if defined ProgramFiles(x86) (
    for %%I in (
        "%ProgramFiles(x86)%\PowerShell\7\pwsh.exe"
        "%ProgramFiles(x86)%\PowerShell\6\pwsh.exe"
    ) do if not defined POWERSHELL_EXE if exist "%%~I" set "POWERSHELL_EXE=%%~I"
)

if not defined POWERSHELL_EXE (
    where /Q powershell.exe
    if not errorlevel 1 set "POWERSHELL_EXE=powershell.exe"
)

if not defined POWERSHELL_EXE (
    where /Q pwsh.exe
    if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"
)

if not defined POWERSHELL_EXE (
    echo.
    echo PowerShell was not found.
    echo Checked the standard Windows PowerShell and PowerShell 7 install locations.
    echo If PowerShell is installed, restore it to PATH or launch this file from PowerShell directly.
    pause
    exit /b 9009
)

:retry
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%LAUNCH_SCRIPT%"
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
