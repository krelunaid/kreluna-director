# Installa Kreluna Director sul PC Windows (cartella utente, niente admin).
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Here "Kreluna Director"
if (-not (Test-Path (Join-Path $Source "apps\director-desktop\kreluna_desktop.py"))) {
    $Source = $Here
}
if (-not (Test-Path (Join-Path $Source "apps\director-desktop\kreluna_desktop.py"))) {
    throw "Non trovo i file di Kreluna accanto a Installa.ps1"
}

$Install = Join-Path $env:LOCALAPPDATA "KrelunaDirector"
$App = Join-Path $Install "app"
New-Item -ItemType Directory -Force -Path $Install | Out-Null
if (Test-Path $App) {
    Remove-Item -Recurse -Force $App
}
New-Item -ItemType Directory -Force -Path $App | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $App -Recurse -Force

foreach ($name in @("Avvia.bat", "Avvia.vbs", "kreluna.ico")) {
    $from = Join-Path $Source $name
    if (Test-Path $from) {
        Copy-Item -Path $from -Destination (Join-Path $Install $name) -Force
    }
}

$Wsh = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$Start = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
New-Item -ItemType Directory -Force -Path $Start | Out-Null
foreach ($folder in @($Desktop, $Start)) {
    $link = $Wsh.CreateShortcut((Join-Path $folder "Kreluna Director.lnk"))
    $link.TargetPath = Join-Path $Install "Avvia.vbs"
    $link.WorkingDirectory = $Install
    $ico = Join-Path $Install "kreluna.ico"
    if (Test-Path $ico) { $link.IconLocation = $ico }
    $link.Save()
}

Write-Host "Kreluna Director e' in $Install"
Write-Host "I dati dello studio restano (cartella data). Chiudi Kreluna prima di aggiornare."
Write-Host "Avvio..."
Start-Process -FilePath (Join-Path $Install "Avvia.vbs")
