@echo off
cd /d "%~dp0"
echo ============================================
echo  ADS Backend - http://localhost:8000
echo  Ctrl+C or close this window to stop.
echo ============================================
python backend\main.py
pause
