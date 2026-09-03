@echo off
rem stop.bat — stop the tender-agent stack (backend + frontend).
rem Double-click, or run from cmd:  stop.bat [backend|frontend]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
