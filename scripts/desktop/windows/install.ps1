# Installe le raccourci JobMail (Bureau + Menu Demarrer). A lancer une fois.
$ErrorActionPreference = "Stop"
$src  = $PSScriptRoot
$dest = Join-Path $env:LOCALAPPDATA "JobMail"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $src "launch.ps1")  $dest -Force
Copy-Item (Join-Path $src "launch.vbs")  $dest -Force
Copy-Item (Join-Path $src "JobMail.ico") $dest -Force

$ws = New-Object -ComObject WScript.Shell
$targets = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
)
foreach ($dir in $targets) {
    $lnk = $ws.CreateShortcut((Join-Path $dir "JobMail.lnk"))
    $lnk.TargetPath       = "wscript.exe"
    $lnk.Arguments        = "`"$dest\launch.vbs`""
    $lnk.IconLocation     = "$dest\JobMail.ico"
    $lnk.WorkingDirectory = $dest
    $lnk.Description       = "JobMail Assistant"
    $lnk.Save()
}
Write-Host "JobMail installe. Raccourci sur le Bureau et le menu Demarrer."
