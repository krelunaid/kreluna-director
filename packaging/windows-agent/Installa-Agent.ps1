# Installa UN Agent Kreluna su questo PC. Non è il Director: è il braccio.
param(
  [Parameter(Mandatory = $true)][string]$Role,
  [string]$DisplayName = "",
  [string]$EnrollCode = "",
  [string]$FattureTarget = ""
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
$DirectorUri = $null
if (-not [Uri]::TryCreate($DirectorUrl, [UriKind]::Absolute, [ref]$DirectorUri)) {
  throw "L'indirizzo del Director non e' valido."
}
$LocalDirector = $DirectorUri.Host -in @("127.0.0.1", "localhost", "::1")
if ($DirectorUri.Scheme -ne "https" -and -not ($DirectorUri.Scheme -eq "http" -and $LocalDirector)) {
  throw "Fuori da questo PC il Director deve usare un indirizzo HTTPS."
}
if (-not [string]::IsNullOrEmpty($DirectorUri.UserInfo) -or -not [string]::IsNullOrEmpty($DirectorUri.Query) -or -not [string]::IsNullOrEmpty($DirectorUri.Fragment) -or $DirectorUri.AbsolutePath -notin @("", "/")) {
  throw "L'indirizzo del Director non e' valido."
}
$DirectorUrl = $DirectorUrl.TrimEnd("/")

if (-not $DisplayName) { $DisplayName = $Role.ToUpper() }
if (-not $EnrollCode) { $EnrollCode = "KRELUNA-" + $Role.ToUpper().Replace("_", "-") }

if ($Role -eq "pc-fatture" -and -not $FattureTarget) {
  $FattureTarget = (Read-Host "Percorso del programma fatture (.exe) o indirizzo HTTPS del portale; Invio per prova locale").Trim()
}
if ($FattureTarget) {
  if ($FattureTarget -match '^https?://') {
    $TargetUri = $null
    if (-not [Uri]::TryCreate($FattureTarget, [UriKind]::Absolute, [ref]$TargetUri)) {
      throw "L'indirizzo fatture non e' valido."
    }
    $LocalTarget = $TargetUri.Host -in @("127.0.0.1", "localhost", "::1")
    if ($TargetUri.Scheme -ne "https" -and -not ($TargetUri.Scheme -eq "http" -and $LocalTarget)) {
      throw "Il portale fatture deve usare HTTPS."
    }
    if (-not [string]::IsNullOrEmpty($TargetUri.UserInfo)) {
      throw "L'indirizzo fatture non deve contenere credenziali."
    }
  } else {
    $FattureTarget = [IO.Path]::GetFullPath($FattureTarget)
    if (-not (Test-Path -LiteralPath $FattureTarget) -or [IO.Path]::GetExtension($FattureTarget) -ne ".exe") {
      throw "Scegli un programma fatture Windows esistente con estensione .exe."
    }
  }
}

$Ws = $DirectorUrl.Replace("http://", "ws://").Replace("https://", "wss://").TrimEnd("/") + "/ws/agent"
$Install = Join-Path $env:LOCALAPPDATA "KrelunaAgent-$Role"
$App = Join-Path $Install "app"
New-Item -ItemType Directory -Force -Path $Install | Out-Null
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force -Path $App | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $App -Recurse -Force
Copy-Item -Path $UrlFile -Destination (Join-Path $Install "director.url") -Force
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Install "fatture.target"), $FattureTarget, $Utf8NoBom)

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
set KRELUNA_FATTURE_TARGET_FILE=%INSTALL%\fatture.target
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
if ($Role -eq "pc-fatture" -and $FattureTarget) { Write-Host "Programma fatture: configurato" }
Start-Process -FilePath (Join-Path $Install "Avvia-Agent.bat")
