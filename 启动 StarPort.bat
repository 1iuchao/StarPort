@echo off
rem ============================================================
rem  StarPort - double-click launcher (NO console window)
rem
rem  Hands the platform over to pythonw.exe, which has no console
rem  at all, then exits immediately. So there is no black window
rem  left for you to accidentally close.
rem
rem  Platform logs go to:  data\logs\platform.log
rem  Want to watch live logs instead?  use the debug launcher
rem  (the .bat with "shows logs" in its name).
rem
rem  NOTE: keep this file PURE ASCII. Chinese text here gets
rem        garbled because cmd.exe parses the file as ANSI before
rem        chcp takes effect.
rem ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "ENTRY=%~dp0run.py"

if not exist "%ENTRY%" goto :no_entry

rem ---- fast probe: pythonw.exe in well-known locations ----
rem      (a plain "if exist" chain is far faster than scanning PATH,
rem       and speed matters here: the console window is visible
rem       until this script exits)
set "PYW="
for %%C in (
    "E:\Python312\pythonw.exe"
    "C:\Python312\pythonw.exe"
    "C:\Python313\pythonw.exe"
    "C:\Python314\pythonw.exe"
    "E:\Python313\pythonw.exe"
    "E:\Python314\pythonw.exe"
    "E:\Python311\pythonw.exe"
    "C:\Python311\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
) do (
    if not defined PYW if exist "%%~C" set "PYW=%%~C"
)

if defined PYW goto :launch

rem ---- fallback: ask the system (only when the above all miss) ----
for /f "delims=" %%P in ('where pythonw 2^>nul') do (
    if not defined PYW set "PYW=%%P"
)
if defined PYW goto :launch

rem ---- last resort: derive pythonw.exe from a plain python.exe on PATH ----
set "PY="
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY set "PY=%%P"
)
if not defined PY goto :no_python
set "PYW=!PY:python.exe=pythonw.exe!"
if not exist "!PYW!" goto :no_python

:launch
rem pythonw.exe creates no console window at all, and `start` + exit
rem closes this script's own console immediately.
start "" "!PYW!" "!ENTRY!"
exit /b 0


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
echo   [ERROR] pythonw.exe not found. Python 3.10+ is required.
echo.
echo   Download: https://www.python.org/downloads/
echo   During install, tick "Add python.exe to PATH".
echo.
echo   You can also try the debug launcher, which shows details.
echo.
pause
exit /b 1
