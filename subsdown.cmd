@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0subsdown.ps1" %*
exit /b %errorlevel%
