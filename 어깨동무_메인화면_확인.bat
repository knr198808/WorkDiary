@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python tools\ekdm_probe.py) || (py -3 tools\ekdm_probe.py)
