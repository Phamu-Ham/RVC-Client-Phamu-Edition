@echo off
setlocal DisableDelayedExpansion
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
echo 起動中… RVC Clientの準備をしています。この画面を閉じずにお待ちください。
cd /d "%~dp0"
"%~dp0runtime\python.exe" -B "%~dp0gui_v1.py"
set "PHAMU_CLIENT_EXIT=%ERRORLEVEL%"
if not "%PHAMU_CLIENT_EXIT%"=="0" echo 起動または実行中にエラーが発生しました。本体のsupport_logsを確認してください。
if not "%PHAMU_CLIENT_EXIT%"=="0" pause
exit /b %PHAMU_CLIENT_EXIT%
