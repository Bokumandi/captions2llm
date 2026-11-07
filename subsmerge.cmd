@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0subsmerge.ps1" %*
exit /b %ERRORLEVEL%
