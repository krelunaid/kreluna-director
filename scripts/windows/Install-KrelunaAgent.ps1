# Installa Kreluna Agent su un PC dello studio (ruolo unico).
# Eseguire da PowerShell dopo aver installato Kreluna Director, oppure dallo zip.

param(
  [string]$Role = "pc-fatture",
  [string]$DirectorUrl = "http://127.0.0.1:8080",
  [string]$EnrollCode = "KRELUNA-PC-FATTURE"
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Install = Join-Path $env:LOCALAPPDATA "KrelunaAgent-$Role"
$App = Join-Path $Install "app"
New-Item -ItemType Directory -Force -Path $Install | Out-Null

$Source = $null
foreach ($candidate in @(
    (Join-Path $Here "Kreluna Director"),
    (Join-Path $env:LOCALAPPDATA "KrelunaDirector\app"),
    (Join-Path $Here "..\..\..")
)) {
    if (Test-Path (Join-Path $candidate "apps\kreluna-agent\agent\main.py")) {
        $Source = $candidate
        break
    }
}
if (-not $Source) {
    throw "Non trovo i file Agent. Installa prima Kreluna Director oppure esegui lo script dallo zip Windows."
}

if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force -Path $App | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $App -Recurse -Force

$Launcher = @"
@echo off
setlocal
set INSTALL=$Install
set ROOT=$App\
set AGENT_DIRECTOR_URL=$DirectorUrl
set AGENT_DIRECTOR_WSS=$($DirectorUrl.Replace('http://','ws://').Replace('https://','wss://'))/ws/agent
set KRELUNA_ENROLLMENT_CODE=$EnrollCode
set KRELUNA_AGENT_ID=$Role
set KRELUNA_AGENT_DISPLAY_NAME=$Role
set KRELUNA_AGENT_DATA_DIR=%INSTALL%\data
if not exist "%INSTALL%\venv\Scripts\python.exe" (
  py -3 -m venv "%INSTALL%\venv" 2>nul || python -m venv "%INSTALL%\venv"
  "%INSTALL%\venv\Scripts\python.exe" -m pip install --upgrade pip
  "%INSTALL%\venv\Scripts\python.exe" -m pip install -e "%ROOT%"
)
set PYTHONPATH=%ROOT%packages\kreluna-shared\src;%ROOT%apps\kreluna-agent
cd /d "%ROOT%"
"%INSTALL%\venv\Scripts\python.exe" -m agent.main
"@
Set-Content -Path (Join-Path $Install "Avvia-Agent.bat") -Value $Launcher -Encoding ASCII

$Wsh = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$link = $Wsh.CreateShortcut((Join-Path $Desktop "Kreluna Agent $Role.lnk"))
$link.TargetPath = Join-Path $Install "Avvia-Agent.bat"
$link.WorkingDirectory = $Install
$link.Save()

Write-Host "Agent $Role installato in $Install"
Write-Host "Director: $DirectorUrl"
Write-Host "Codice enrollment: $EnrollCode"
Write-Host "Sul desktop: Kreluna Agent $Role"
# Nessuna backdoor, nessun blocco di Windows, nessuna chiave server in questo script.
