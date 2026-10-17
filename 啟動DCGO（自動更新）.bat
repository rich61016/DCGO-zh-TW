@echo off
setlocal EnableExtensions
chcp 65001 >nul
title DCGO zh-TW - auto update
rem Double-click: check the official DCGO update server, download changed files,
rem re-apply the Traditional Chinese localization, then start the game.
rem (Chinese messages are in _zh_tools\msg\*.txt so this file can stay plain ASCII.)
rem The tools need Python 3.9 - 3.14 (UnityPy and some dependencies have no wheels for 3.15 yet).
set "TOOLS=%~dp0_zh_tools"
set "MSG=%~dp0_zh_tools\msg"
set "VENV=%~dp0_zh_tools\.venv-win"
set "VPY=%~dp0_zh_tools\.venv-win\Scripts\python.exe"
if not exist "%TOOLS%\zh_update.py" goto nodir
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist "%VPY%" goto checkvenv

:create
type "%MSG%\first_run.txt"
call :findpy
if not defined PYEXE goto nopython

:mkvenv
echo Python: %PYEXE%
"%PYEXE%" -m venv "%VENV%"
if errorlevel 1 goto fail
"%VPY%" -m pip install -q --disable-pip-version-check "UnityPy==1.25.4" "opencc-python-reimplemented==0.1.7"
if errorlevel 1 goto piperror
goto run

:checkvenv
rem the environment must be a supported Python version and have UnityPy installed
"%VPY%" -c "import sys, UnityPy; sys.exit(0 if (3, 9) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>nul
if not errorlevel 1 goto checkcc
type "%MSG%\venv_broken.txt"
rmdir /s /q "%VENV%"
goto create

:checkcc
rem card text (Simplified -> Traditional Chinese) needs OpenCC; add it to older environments
rem (if this fails, only the card text step is skipped)
"%VPY%" -c "import opencc" >nul 2>nul
if not errorlevel 1 goto run
"%VPY%" -m pip install -q --disable-pip-version-check "opencc-python-reimplemented==0.1.7"
goto run

:run
"%VPY%" "%TOOLS%\zh_update.py" --launch
if errorlevel 1 goto failrun
type "%MSG%\done.txt"
timeout /t 5 >nul
exit /b 0

:nopython
type "%MSG%\no_python.txt"
echo [where py]
where py 2>nul
echo [where python]
where python 2>nul
echo.
where winget >nul 2>nul
if errorlevel 1 goto manual
type "%MSG%\ask_install.txt"
choice /C YN /N /M "Install Python 3.13 now? [Y/N] "
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
call :findpy
if defined PYEXE goto mkvenv
type "%MSG%\python_installed_restart.txt"
goto fail

:manual
type "%MSG%\python_manual.txt"
start "" "https://www.python.org/downloads/windows/"
goto fail

:piperror
type "%MSG%\pip_failed.txt"
rmdir /s /q "%VENV%" >nul 2>nul
pause
exit /b 1

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
rem Find Python 3.9 - 3.14: the py launcher with explicit versions, python,
rem python3, then the usual install folders (works even if not on PATH).
:findpy
set "PYEXE="
for %%V in (3.13 3.12 3.14 3.11 3.10 3.9) do if not defined PYEXE call :trycmd py -%%V
if not defined PYEXE call :trycmd python
if not defined PYEXE call :trycmd python3
if defined PYEXE exit /b 0
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if not defined PYEXE if exist "%%~D\python.exe" call :trycmd "%%~D\python.exe"
for /d %%D in ("%LocalAppData%\Python\pythoncore-3*") do if not defined PYEXE if exist "%%~D\python.exe" call :trycmd "%%~D\python.exe"
for /d %%D in ("%ProgramFiles%\Python3*") do if not defined PYEXE if exist "%%~D\python.exe" call :trycmd "%%~D\python.exe"
exit /b 0

:trycmd
set "PYOUT="
rem "call" keeps cmd from stripping the quotes when the command starts with a quoted path
for /f "usebackq delims=" %%P in (`call %* -c "import sys; print(sys.executable if (3, 9) <= sys.version_info[:2] < (3, 15) else '')" 2^>nul`) do set "PYOUT=%%P"
if defined PYOUT if exist "%PYOUT%" set "PYEXE=%PYOUT%"
exit /b 0
