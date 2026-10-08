@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
call "%~dp0运行环境.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
"%NVB_PYTHON%" -X utf8 "%~dp0引擎\schedule_task.py" remove
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
