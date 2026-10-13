@echo off
cd /d "%~dp0"
set PY=
where pythonw >nul 2>nul && set PY=pythonw
if not defined PY where pyw >nul 2>nul && set PY=pyw -3
if not defined PY (
  echo Python is not installed. Install from https://www.python.org/downloads/ and check "Add python.exe to PATH".
  pause
  exit /b
)
where python >nul 2>nul && (python -c "import qrcode" >nul 2>nul || python -m pip install -q qrcode)
start "" %PY% WorkDiary.pyw
