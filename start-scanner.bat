@echo off
cd /d "%~dp0"
:loop
python worker.py
echo Scanner stopped. Restarting in 10 seconds...
timeout /t 10 /nobreak >nul
goto loop
