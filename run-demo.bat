@echo off
REM Start ParcelDesk in demo mode (simulated carriers, no credentials needed).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
)
if not exist ".env" copy .env.example .env >nul
echo ParcelDesk (demo) -^> http://localhost:8000   login: admin@example.com / admin123
.venv\Scripts\python.exe run.py --demo --host 0.0.0.0 --port 8000
pause
