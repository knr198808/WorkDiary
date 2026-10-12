@echo off
cd /d %~dp0
pip install pyinstaller
pyinstaller --onefile --noconsole --name WorkDiary WorkDiary.pyw
echo.
echo ¿Ï·á: dist\WorkDiary.exe
pause
