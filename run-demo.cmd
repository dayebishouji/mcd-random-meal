@echo off
cd /d "%~dp0"
python -X utf8 scripts\main.py demo %*
if errorlevel 1 goto failed
start "" "local\demo.html"
exit /b 0
:failed
echo Demo did not complete. Please check Python 3.10 or newer is installed.
pause
exit /b 1
