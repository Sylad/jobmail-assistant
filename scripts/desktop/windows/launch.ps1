# Orchestrateur de l'app de bureau JobMail — propriétaire du cycle de vie.
$ErrorActionPreference = "Stop"
$Distro    = "Ubuntu"
$RepoLinux = "/home/sylvain_ladoire/projects/developpeur/jobmail-assistant"
$Url       = "http://localhost:8765"
$EdgeProfile = Join-Path $env:LOCALAPPDATA "JobMail\edge-profile"

$Edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $Edge)) { $Edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" }
if (-not (Test-Path $Edge)) {
    $Edge = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"  # fallback
}

function Test-Up {
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url).StatusCode -eq 200 }
    catch { $false }
}
function Open-Window {
    Start-Process $Edge -PassThru -ArgumentList @(
        "--app=$Url",
        "--user-data-dir=`"$EdgeProfile`"",
        "--window-size=1400,900"
    )
}
function Show-Error([string]$msg) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($msg, "JobMail") | Out-Null
}

# 1. Déjà lancé ? On ouvre juste une nouvelle fenêtre, pas de 2e stack.
if (Test-Up) { Open-Window | Out-Null; return }

# 2. Démarrer le backend dans WSL.
wsl.exe -d $Distro -e bash -lc "'$RepoLinux/scripts/desktop/start.sh'" | Out-Null

# 3. Attendre que :8765 réponde (30s max).
$ready = $false
for ($i = 0; $i -lt 30; $i++) { if (Test-Up) { $ready = $true; break }; Start-Sleep -Seconds 1 }
if (-not $ready) {
    $log = (wsl.exe -d $Distro -e bash -lc "tail -n 20 ~/.jobmail/jobmail.log 2>/dev/null") -join "`n"
    wsl.exe -d $Distro -e bash -lc "'$RepoLinux/scripts/desktop/stop.sh'" | Out-Null
    Show-Error "JobMail n'a pas demarre en 30s.`n`n$log"
    return
}

# 4. Ouvrir la fenetre dediee et bloquer jusqu'a sa fermeture.
$win = Open-Window
$win.WaitForExit()

# 5. Tout eteindre.
wsl.exe -d $Distro -e bash -lc "'$RepoLinux/scripts/desktop/stop.sh'" | Out-Null
