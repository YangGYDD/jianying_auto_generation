@echo off
set "NVB_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%NVB_PYTHON%" set "NVB_PYTHON=%~dp0runtime\python.exe"
if not exist "%NVB_PYTHON%" (
  echo Please run setup first: python -m venv .venv
  exit /b 1
)
exit /b 0
