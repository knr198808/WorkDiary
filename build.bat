@echo off
cd /d %~dp0
pip install pyinstaller qrcode
pyinstaller --onefile --noconsole --name WorkDiary WorkDiary.pyw
echo.
echo Done: dist\WorkDiary.exe
pause
