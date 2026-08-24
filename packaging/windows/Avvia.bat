@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "INSTALL=%LOCALAPPDATA%\KrelunaDirector"
set "ROOT=%~dp0"
if not exist "%ROOT%apps\director-desktop\kreluna_desktop.py" (
  set "ROOT=%INSTALL%\app\"
)

if not exist "%ROOT%apps\director-desktop\kreluna_desktop.py" (
  echo Non trovo Kreluna. Esegui prima Installa.bat
  pause
  exit /b 1
)

if not exist "%INSTALL%\venv\Scripts\python.exe" (
  echo Prima apertura: sto preparando Kreluna...
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    py -3 -m venv "%INSTALL%\venv"
  ) else (
    python -m venv "%INSTALL%\venv"
  )
  if errorlevel 1 (
    echo Serve Python 3.11 o piu nuovo: https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
  "%INSTALL%\venv\Scripts\python.exe" -m pip install --upgrade pip
  "%INSTALL%\venv\Scripts\python.exe" -m pip install -e "%ROOT%"
)

set "PYTHONPATH=%ROOT%packages\kreluna-shared\src;%ROOT%apps\director-api;%ROOT%apps\kreluna-agent;%ROOT%apps\director-desktop"
set "DIRECTOR_DATABASE_URL=sqlite+aiosqlite:///%INSTALL%\data\kreluna.db"
set "DIRECTOR_EVIDENCE_DIR=%INSTALL%\data\evidence"
set "KRELUNA_AGENT_DATA_DIR=%INSTALL%\data\agent"
set "AGENT_DIRECTOR_URL=http://127.0.0.1:8080"
set "AGENT_DIRECTOR_WSS=ws://127.0.0.1:8080/ws/agent"
set "KRELUNA_ENROLLMENT_CODE=KRELUNA-DEV-ENROLL"
set "KRELUNA_AGENT_ID=pc-studio"
set "KRELUNA_AGENT_DISPLAY_NAME=PC-STUDIO"

cd /d "%ROOT%"
"%INSTALL%\venv\Scripts\python.exe" "%ROOT%apps\director-desktop\kreluna_desktop.py"
