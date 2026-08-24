# Installa UN Agent Kreluna su questo PC. Non è il Director: è il braccio.
param(
  [Parameter(Mandatory = $true)][string]$Role,
  [string]$DisplayName = "",
  [string]$EnrollCode = ""
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Here "Kreluna Agent"
if (-not (Test-Path (Join-Path $Source "apps\kreluna-agent\agent\main.py"))) {
  throw "Apri lo zip Kreluna-Agenti-Windows e lancia Installa da li."
}

$UrlFile = Join-Path $Here "director.url"
if (-not (Test-Path $UrlFile)) {
  throw "Manca director.url. Scrivi dentro l'indirizzo del Director (es. http://192.168.1.10:8080)."
}
$DirectorUrl = (Get-Content $UrlFile -Raw).Trim().Split("`n")[0].Trim()
if (-not $DirectorUrl) {
  throw "director.url e' vuoto. Metti l'indirizzo del Director."
}

if (-not $DisplayName) { $DisplayName = $Role.ToUpper() }
if (-not $EnrollCode) { $EnrollCode = "KRELUNA-" + $Role.ToUpper().Replace("_", "-") }

$Ws = $DirectorUrl.Replace("http://", "ws://").Replace("https://", "wss://").TrimEnd("/") + "/ws/agent"
$Install = Join-Path $env:LOCALAPPDATA "KrelunaAgent-$Role"
$App = Join-Path $Install "app"
New-Item -ItemType Directory -Force -Path $Install | Out-Null
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force -Path $App | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $App -Recurse -Force
Copy-Item -Path $UrlFile -Destination (Join-Path $Install "director.url") -Force

$Py = Join-Path $App "runtime\python.exe"
if (-not (Test-Path $Py)) {
  throw "Manca Python nello zip Agent. Scarica di nuovo Kreluna-Agenti-Windows.zip."
}

$Launcher = @"
@echo off
setlocal
set INSTALL=$Install
set ROOT=$App\
for /f "usebackq delims=" %%U in ("%INSTALL%\director.url") do (
  set "AGENT_DIRECTOR_URL=%%U"
  goto :goturl
)
:goturl
set "AGENT_DIRECTOR_WSS=%AGENT_DIRECTOR_URL:http://=ws://%"
set "AGENT_DIRECTOR_WSS=%AGENT_DIRECTOR_WSS:https://=wss://%/ws/agent"
set KRELUNA_ENROLLMENT_CODE=$EnrollCode
set KRELUNA_AGENT_ID=$Role
set KRELUNA_AGENT_DISPLAY_NAME=$DisplayName
set KRELUNA_AGENT_DATA_DIR=%INSTALL%\data
set PYTHONHOME=%ROOT%runtime
set PYTHONPATH=%ROOT%packages\kreluna-shared\src;%ROOT%apps\kreluna-agent
cd /d "%ROOT%"
"%ROOT%runtime\python.exe" -m agent.main
if errorlevel 1 pause
"@
Set-Content -Path (Join-Path $Install "Avvia-Agent.bat") -Value $Launcher -Encoding ASCII

$Wsh = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$link = $Wsh.CreateShortcut((Join-Path $Desktop "Kreluna Agent $DisplayName.lnk"))
$link.TargetPath = Join-Path $Install "Avvia-Agent.bat"
$link.WorkingDirectory = $Install
$link.Save()

Write-Host "Agent $DisplayName installato. Non e' il Director: questo PC esegue solo il suo lavoro."
Write-Host "Director: $DirectorUrl"
Start-Process -FilePath (Join-Path $Install "Avvia-Agent.bat")
