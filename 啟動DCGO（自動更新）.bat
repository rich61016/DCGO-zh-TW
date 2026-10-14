@echo off
setlocal EnableExtensions
chcp 65001 >nul
title DCGO zh-TW - auto update
rem Double-click: check the official DCGO update server, download changed files,
rem re-apply the Traditional Chinese localization, then start the game.
rem (Chinese messages are in _zh_tools\msg\*.txt so this file can stay plain ASCII.)
set "TOOLS=%~dp0_zh_tools"
set "MSG=%~dp0_zh_tools\msg"
if not exist "%TOOLS%\zh_update.py" goto nodir
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "VPY=%TOOLS%\.venv-win\Scripts\python.exe"
if exist "%VPY%" goto run

type "%MSG%\first_run.txt"
call :findpy
if defined PYEXE goto mkvenv

type "%MSG%\no_python.txt"
echo [where py]
where py 2>nul
echo [where python]
where python 2>nul
echo.
where winget >nul 2>nul
if errorlevel 1 goto manual
type "%MSG%\ask_install.txt"
choice /C YN /N /M "Install Python 3.12 now? [Y/N] "
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :findpy
if defined PYEXE goto mkvenv
type "%MSG%\python_installed_restart.txt"
goto fail

:manual
type "%MSG%\python_manual.txt"
start "" "https://www.python.org/downloads/"
goto fail

:mkvenv
echo Python: %PYEXE%
"%PYEXE%" -m venv "%TOOLS%\.venv-win"
if errorlevel 1 goto fail
"%VPY%" -m pip install -q --disable-pip-version-check "UnityPy==1.25.4"
if errorlevel 1 goto fail

:run
rem repair a half-finished environment (e.g. an earlier pip install was interrupted)
"%VPY%" -c "import UnityPy" >nul 2>nul
if errorlevel 1 "%VPY%" -m pip install -q --disable-pip-version-check "UnityPy==1.25.4"
"%VPY%" "%TOOLS%\zh_update.py" --launch
if errorlevel 1 goto failrun
type "%MSG%\done.txt"
timeout /t 5 >nul
exit /b 0

:failrun
type "%MSG%\failrun.txt"
pause
exit /b 1

:nodir
echo [ERROR] _zh_tools\zh_update.py not found. Keep this .bat in the game folder.
pause
exit /b 1

:fail
type "%MSG%\fail.txt"
pause
exit /b 1

rem ---------------------------------------------------------------
rem Find Python 3.9+: try the py launcher, python, python3, then the
rem usual install folders (works even if Python is not on PATH).
:findpy
set "PYEXE="
call :trycmd py -3
if not defined PYEXE call :trycmd python
if not defined PYEXE call :trycmd python3
if defined PYEXE exit /b 0
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if not defined PYEXE if exist "%%~D\python.exe" call :trycmd "%%~D\python.exe"
for /d %%D in ("%ProgramFiles%\Python3*") do if not defined PYEXE if exist "%%~D\python.exe" call :trycmd "%%~D\python.exe"
exit /b 0

:trycmd
set "PYOUT="
rem "call" keeps cmd from stripping the quotes when the command starts with a quoted path
for /f "usebackq delims=" %%P in (`call %* -c "import sys; print(sys.executable if sys.version_info[:2] >= (3, 9) else '')" 2^>nul`) do set "PYOUT=%%P"
if defined PYOUT if exist "%PYOUT%" set "PYEXE=%PYOUT%"
exit /b 0
