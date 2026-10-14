@echo off
chcp 65001 >nul
setlocal EnableExtensions
title DCGO 繁中化 自動更新
rem 雙擊執行:檢查 DCGO 官方更新 -> 有新版就下載有變動的檔案並重新套用繁體中文化 -> 啟動遊戲
rem 更新來源與官方啟動器相同 https://dcgo.online/PATCH ,每個檔案下載後都會驗證雜湊
cd /d "%~dp0_zh_tools"
if errorlevel 1 goto nodir
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "VPY=%~dp0_zh_tools\.venv-win\Scripts\python.exe"
if exist "%VPY%" goto run

echo 第一次使用：建立中文化工具需要的 Python 環境，會從 pypi.org 下載約 30 MB…
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto mkvenv
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto mkvenv
echo.
echo 找不到 Python 3.9 以上的版本。
echo 請到 https://www.python.org/downloads/ 下載安裝，安裝時勾選「Add python.exe to PATH」，然後再執行一次這個檔案。
goto fail

:mkvenv
%PYCMD% -m venv "%~dp0_zh_tools\.venv-win"
if errorlevel 1 goto fail
"%VPY%" -m pip install -q --disable-pip-version-check "UnityPy==1.25.4"
if errorlevel 1 goto fail

:run
"%VPY%" "%~dp0_zh_tools\zh_update.py" --launch
if errorlevel 1 goto failrun
echo.
echo 完成，這個視窗會在幾秒後自動關閉。
timeout /t 5 >nul
exit /b 0

:failrun
echo.
echo 更新過程有問題，請看上方訊息。遊戲仍可用目前的版本遊玩。
pause
exit /b 1

:nodir
echo 找不到 _zh_tools 資料夾，請確認這個檔案放在遊戲資料夾裡。
pause
exit /b 1

:fail
echo.
echo 建立 Python 環境失敗，請把上面的訊息告訴 Claude。
pause
exit /b 1
