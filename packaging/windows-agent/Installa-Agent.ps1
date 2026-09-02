# Installa UN Agent Kreluna su questo PC. Non è il Director: è il braccio.
param(
  [string]$ConnectionCode = "",
  [string]$Role = "",
  [string]$DisplayName = "",
  [string]$DirectorUrl = "",
  [string]$EnrollCode = "",
  [string]$FattureTarget = ""
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Here "Kreluna Agent"
if (-not (Test-Path (Join-Path $Source "apps\kreluna-agent\agent\main.py"))) {
  throw "Apri lo zip Kreluna-Agenti-Windows e lancia Installa da li."
}

$PairingPrefix = "KRELUNA-COLLEGA-1."
if (-not $ConnectionCode -and (-not $Role -or -not $DirectorUrl -or -not $EnrollCode)) {
  $ConnectionCode = (Read-Host "Incolla il Codice di collegamento copiato dal Director").Trim()
}
if ($ConnectionCode) {
  $CompactCode = $ConnectionCode -replace '\s', ''
  if (-not $CompactCode.StartsWith($PairingPrefix) -or $CompactCode.Length -gt 1200) {
    throw "Codice di collegamento Kreluna non valido."
  }
  try {
    $Encoded = $CompactCode.Substring($PairingPrefix.Length).Replace('-', '+').Replace('_', '/')
    switch ($Encoded.Length % 4) {
      2 { $Encoded += "==" }
      3 { $Encoded += "=" }
      1 { throw "Codifica non valida" }
    }
    $Linked = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Encoded)) | ConvertFrom-Json
  } catch {
    throw "Codice di collegamento Kreluna non leggibile."
  }
  if ($Linked.v -ne 1 -or -not $Linked.u -or -not $Linked.r -or -not $Linked.n -or -not $Linked.c) {
    throw "Dati mancanti nel Codice di collegamento."
  }
  $DirectorUrl = [string]$Linked.u
  $Role = [string]$Linked.r
  $DisplayName = [string]$Linked.n
  $EnrollCode = [string]$Linked.c
}

$UrlFile = Join-Path $Here "director.url"
$DefaultDirectorUrl = if (Test-Path $UrlFile) { (Get-Content $UrlFile -Raw).Trim().Split("`n")[0].Trim() } else { "" }
if (-not $DirectorUrl) {
  $TypedDirectorUrl = (Read-Host "Indirizzo Director mostrato in Impostazioni/PC remoti [$DefaultDirectorUrl]").Trim()
  $DirectorUrl = if ($TypedDirectorUrl) { $TypedDirectorUrl } else { $DefaultDirectorUrl }
}
if ($Role -notmatch '^pc-[a-z0-9-]{2,60}$') {
  throw "Lavoro Agent non valido."
}
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
if ($DisplayName.Length -gt 120) { throw "Nome Agent non valido." }
if (-not $EnrollCode) {
  $EnrollCode = (Read-Host "Codice monouso generato dal Director").Trim()
}
if (-not $EnrollCode.StartsWith("KRELUNA-ENROLL-") -or $EnrollCode.Length -lt 50 -or $EnrollCode.Length -gt 100) {
  throw "Usa il codice monouso generato dal Director."
}

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
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Install "director.url"), $DirectorUrl, $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Install "fatture.target"), $FattureTarget, $Utf8NoBom)
$EnrollPath = Join-Path $Install "enrollment.once"
[IO.File]::WriteAllText($EnrollPath, $EnrollCode, $Utf8NoBom)

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
set KRELUNA_ENROLLMENT_CODE_FILE=%INSTALL%\enrollment.once
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
