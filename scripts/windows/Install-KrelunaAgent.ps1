# Installa Kreluna Agent su Windows (PC dello studio)
# Eseguire in PowerShell come utente dello studio, una volta per PC.

param(
  [string]$Role = "pc-fatture",
  [string]$DirectorUrl = "http://127.0.0.1:8080",
  [string]$EnrollCode = "KRELUNA-PC-FATTURE"
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "KrelunaAgent"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host "Kreluna Agent ruolo $Role"
Write-Host "Director: $DirectorUrl"
Write-Host "Codice enrollment: $EnrollCode"
Write-Host "Copia qui il progetto Kreluna e avvia:"
Write-Host "  `$env:KRELUNA_AGENT_ID='$Role'"
Write-Host "  `$env:KRELUNA_ENROLLMENT_CODE='$EnrollCode'"
Write-Host "  `$env:AGENT_DIRECTOR_URL='$DirectorUrl'"
Write-Host "  python -m agent.main"

# Nessuna backdoor, nessun blocco di Windows, nessuna chiave server in questo script.
