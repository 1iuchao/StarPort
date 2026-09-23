@echo off
rem ============================================================
rem  StarPort - local app aggregation platform
rem  Double-click this file to start. Keep this window open.
rem  NOTE: keep this file pure ASCII. Chinese text here will be
rem        garbled because cmd.exe parses the file as ANSI before
rem        chcp takes effect. All Chinese output comes from
rem        tools\bootstrap.py instead.
rem ============================================================

chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title StarPort

set "ROOT=%~dp0"
set "ENTRY=%ROOT%run.py"
set "BOOT=%ROOT%tools\bootstrap.py"

if not exist "%ENTRY%" goto :no_entry

rem ---- 1) interpreter recorded in the platform config ----
set "PY="
set "CFG=%ROOT%data\config.json"
if exist "%CFG%" (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "try{(Get-Content -LiteralPath '%CFG%' -Raw -Encoding UTF8 ^| ConvertFrom-Json).platform.python_path}catch{''}"`) do (
        if exist "%%P" set "PY=%%P"
    )
)

rem ---- 2) probe well-known locations ----
if not defined PY (
    for %%C in (
        "E:\Python312\python.exe"
        "C:\Python312\python.exe"
        "C:\Python313\python.exe"
        "C:\Python314\python.exe"
        "E:\Python313\python.exe"
        "E:\Python314\python.exe"
        "E:\Python311\python.exe"
        "C:\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) do (
        if not defined PY if exist "%%~C" set "PY=%%~C"
    )
)

rem ---- 3) py launcher, then PATH ----
set "PYARGS="
if not defined PY (
    if exist "%SystemRoot%\py.exe" (
        set "PY=%SystemRoot%\py.exe"
        set "PYARGS=-3"
    )
)
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PY set "PY=%%P"
    )
)

if not defined PY goto :no_python

rem ---- 4) start: banner + version check + launch, all in python ----
"!PY!" !PYARGS! "!BOOT!" "!ENTRY!" "!PY!"
set "RC=!ERRORLEVEL!"

echo.
if "!RC!"=="0" (
    echo   StarPort stopped normally. / StarPort yi zheng chang tui chu.
) else (
    echo   StarPort exited with code !RC!
)
echo.
pause
endlocal
exit /b !RC!


:no_entry
echo.
echo   [ERROR] run.py not found.
echo   Expected: %ENTRY%
echo   Put this .bat in the StarPort root folder.
echo.
pause
exit /b 1

:no_python
echo.
echo   [ERROR] Python not found. Python 3.10+ is required.
echo   Download: https://www.python.org/downloads/
echo   During install, tick "Add python.exe to PATH".
echo.
pause
exit /b 1

:bad_python
echo.
echo   [ERROR] Cannot run Python: %PY%
echo.
pause
exit /b 1

:old_python
echo.
echo   [ERROR] Python too old: !VER!  (need 3.10+)
echo   Interpreter: %PY%
echo.
pause
exit /b 1
