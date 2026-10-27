@echo off
rem Double-click this file to start IndQuant Terminal. Keep the window open; close it to stop the app.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
