@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
call "%~dp0运行环境.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
set "NEWS_COUNT=5"
set /p "NEWS_COUNT=请输入成功草稿数量（默认5）："
"%NVB_PYTHON%" -X utf8 "%~dp0引擎\automation.py" --manual --count "%NEWS_COUNT%"
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
