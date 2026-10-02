@echo off
REM ParcelDesk launcher for Windows — double-click to start the platform.
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Creating the virtual environment...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
)

if not exist ".env" (
  echo No .env found - copying the template.
  copy .env.example .env >nul
  echo Edit .env to add your DHL / FedEx / Aramex credentials.
  notepad .env
)

echo.
echo Starting ParcelDesk on http://localhost:8000
echo Open that address in your browser. Press Ctrl+C in this window to stop.
echo.
.venv\Scripts\python.exe run.py --host 0.0.0.0 --port 8000
pause
