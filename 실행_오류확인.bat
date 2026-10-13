@echo off
cd /d "%~dp0"
echo Running with console to show errors...
where python >nul 2>nul && (python WorkDiary.pyw) || (py -3 WorkDiary.pyw)
echo.
echo Exit code: %errorlevel%
pause
