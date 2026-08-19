@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" backend\server.py
  exit /b
)

where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 backend\server.py
  exit /b
)

where python >nul 2>nul
if %errorlevel% equ 0 (
  python backend\server.py
  exit /b
)

echo Python 3 nao foi encontrado. Instale-o e consulte o README.md.
exit /b 1
