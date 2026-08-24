@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "INSTALL=%LOCALAPPDATA%\KrelunaDirector"
set "ROOT=%~dp0"
if not exist "%ROOT%apps\director-desktop\kreluna_desktop.py" (
  set "ROOT=%INSTALL%\app\"
)

if not exist "%ROOT%apps\director-desktop\kreluna_desktop.py" (
  echo Non trovo Kreluna. Esegui Installa.bat dallo zip.
  pause
  exit /b 1
)

set "PY=%ROOT%runtime\python.exe"
if not exist "%PY%" (
  echo Kreluna e' incompleta. Reinstalla dallo zip nuovo.
  pause
  exit /b 1
)

set "PYTHONHOME=%ROOT%runtime"
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
"%PY%" "%ROOT%apps\director-desktop\kreluna_desktop.py"
