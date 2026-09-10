@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tun_helper.ps1" %*
exit /b %errorlevel%
