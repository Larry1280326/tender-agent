@echo off
rem start.bat — start the tender-agent stack (backend + frontend).
rem Double-click, or run from cmd:  start.bat [backend|frontend]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
