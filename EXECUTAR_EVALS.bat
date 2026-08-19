@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "CLARA_PYTHON=.venv\Scripts\python.exe"
  goto run
)

where py >nul 2>nul
if %errorlevel% equ 0 (
  set "CLARA_PYTHON=py -3"
  goto run
)

where python >nul 2>nul
if %errorlevel% equ 0 (
  set "CLARA_PYTHON=python"
  goto run
)

echo Python 3 nao foi encontrado. Instale-o e consulte o README.md.
exit /b 1

:run
%CLARA_PYTHON% evals\run_evals.py
if errorlevel 1 exit /b %errorlevel%
%CLARA_PYTHON% evals\run_conversation_evals.py
exit /b %errorlevel%
