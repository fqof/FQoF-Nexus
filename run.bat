@echo off
title FQoF · Nexus
echo [FQoF · Nexus] Launching application...
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] An error occurred while running FQoF · Nexus.
    echo Please ensure Python 3.10+ and PyQt6 are installed.
    echo Run: pip install PyQt6
    echo.
    pause
)
