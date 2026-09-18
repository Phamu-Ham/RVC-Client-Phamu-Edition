@echo off
cd /d "%~dp0"
"%~dp0runtime\python.exe" -B "%~dp0gui_v1.py"
if errorlevel 1 pause
