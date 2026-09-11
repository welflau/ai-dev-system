@echo off
setlocal

rem UEEditorMCP setup wrapper. The PowerShell script owns environment probing,
rem dependency install, and MCP client config merging.
set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%setup_mcp.ps1"

if not exist "%PS_SCRIPT%" (
    echo [ERROR] setup_mcp.ps1 not found: %PS_SCRIPT%
    pause
    exit /b 1
)

set "PS_EXE="
for %%P in (pwsh.exe powershell.exe) do (
    if not defined PS_EXE (
        for /f "delims=" %%I in ('where %%P 2^>nul') do (
            if not defined PS_EXE set "PS_EXE=%%I"
        )
    )
)

if not defined PS_EXE (
    echo [ERROR] PowerShell was not found in PATH.
    echo         Please install PowerShell or run setup_mcp.ps1 manually.
    pause
    exit /b 1
)

echo ============================================
echo  UEEditorMCP - Python Environment Setup
echo ============================================
echo.
echo PowerShell: %PS_EXE%
echo Script:     %PS_SCRIPT%
echo.

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Setup failed with exit code %EXIT_CODE%.
    pause
    exit /b %EXIT_CODE%
)

echo.
echo [OK] Setup completed successfully.
pause
exit /b 0
