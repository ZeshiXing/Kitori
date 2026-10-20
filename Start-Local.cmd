@echo off
powershell.exe -NoProfile -File "%~dp0scripts\launch.ps1" -Mode local
if errorlevel 1 pause

