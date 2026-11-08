@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0subsbatch.ps1" %*
exit /b %ERRORLEVEL%
