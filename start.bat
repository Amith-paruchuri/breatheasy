@echo off
REM One-command start for Windows: double-click start.bat
REM First run installs everything (a few minutes). Then open http://localhost:5173
cd /d "%~dp0"

where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
where npm >nul 2>nul || (echo Node.js 18+ is required: https://nodejs.org/ & pause & exit /b 1)

cd backend
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env (copy .env.example .env >nul & echo Created backend\.env - PROVIDER=open: real data, no key needed)
start "Breatheasy backend" cmd /k ".venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
cd ..\frontend
if not exist node_modules call npm install --no-audit --no-fund
echo.
echo Breatheasy is starting at http://localhost:5173  (close both windows to stop)
echo On your phone (same Wi-Fi): http://YOUR-COMPUTER-IP:5173  (find it with: ipconfig)
echo.
start "" http://localhost:5173
call npx vite --port 5173
