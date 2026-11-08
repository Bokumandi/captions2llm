@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0captions2llm.ps1" %*
exit /b %ERRORLEVEL%
