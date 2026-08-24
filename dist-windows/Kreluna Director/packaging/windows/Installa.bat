@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installa.ps1"
if errorlevel 1 pause
