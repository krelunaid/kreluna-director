# Installa Kreluna Agent su un PC dello studio (ruolo unico).
# Eseguire da PowerShell dopo aver installato Kreluna Director, oppure dallo zip.

param(
  [string]$Role = "pc-fatture",
  [string]$DirectorUrl = "http://127.0.0.1:8080",
  [Parameter(Mandatory = $true)][string]$EnrollCode,
  [string]$FattureTarget = ""
)

$ErrorActionPreference = "Stop"
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
if (-not $EnrollCode.StartsWith("KRELUNA-ENROLL-") -or $EnrollCode.Length -lt 50 -or $EnrollCode.Length -gt 100) {
    throw "Usa il codice monouso generato dal Director."
}
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Install = Join-Path $env:LOCALAPPDATA "KrelunaAgent-$Role"
$App = Join-Path $Install "app"
New-Item -ItemType Directory -Force -Path $Install | Out-Null
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Install "fatture.target"), $FattureTarget, $Utf8NoBom)
$EnrollPath = Join-Path $Install "enrollment.once"
[IO.File]::WriteAllText($EnrollPath, $EnrollCode, $Utf8NoBom)

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

$Py = Join-Path $App "runtime\python.exe"
if (-not (Test-Path $Py)) {
    throw "Manca il runtime di Kreluna nello zip. Usa lo zip Windows completo."
}

$Launcher = @"
@echo off
setlocal
set INSTALL=$Install
set ROOT=$App\
set AGENT_DIRECTOR_URL=$DirectorUrl
set AGENT_DIRECTOR_WSS=$($DirectorUrl.Replace('http://','ws://').Replace('https://','wss://'))/ws/agent
set KRELUNA_ENROLLMENT_CODE_FILE=%INSTALL%\enrollment.once
set KRELUNA_AGENT_ID=$Role
set KRELUNA_AGENT_DISPLAY_NAME=$Role
set KRELUNA_AGENT_DATA_DIR=%INSTALL%\data
set KRELUNA_FATTURE_TARGET_FILE=%INSTALL%\fatture.target
set PYTHONHOME=%ROOT%runtime
set PYTHONPATH=%ROOT%packages\kreluna-shared\src;%ROOT%apps\kreluna-agent
cd /d "%ROOT%"
"%ROOT%runtime\python.exe" -m agent.main
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
Write-Host "Sul desktop: Kreluna Agent $Role"
# Nessuna backdoor, nessun blocco di Windows, nessuna chiave server in questo script.
