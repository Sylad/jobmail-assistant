# JobMail Desktop App Launcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lancer JobMail comme une appli Windows : double-clic sur une icône → fenêtre dédiée (Edge `--app`) ; fermer la fenêtre → ollama (si démarré par JobMail) + uvicorn s'éteignent.

**Architecture:** Couche *launcher* pure, aucune modification du code Python. Côté WSL, deux scripts bash (`start.sh`/`stop.sh`) gèrent ollama-smart + uvicorn avec PID files + marqueur. Côté Windows, un orchestrateur PowerShell (`launch.ps1`, lancé caché par `launch.vbs`) démarre le backend dans WSL, attend `:8765`, ouvre la fenêtre Edge, et sur `WaitForExit` appelle `stop.sh`.

**Tech Stack:** Bash, PowerShell, VBScript, WSL2 (Ubuntu), Edge `--app`, Python/Pillow (génération d'icône uniquement), pytest existant non touché.

## Global Constraints

- Aucune modification du code de l'app Python (`jobmail/**`). Launcher pur.
- Distro WSL : `Ubuntu`. Repo Linux : `/home/sylvain_ladoire/projects/developpeur/jobmail-assistant`.
- App URL : `http://localhost:8765` (uvicorn bind `127.0.0.1:8765`, forwardé vers Windows par WSL2).
- Ollama bin : `~/.local/ollama/bin/ollama`. Ollama URL : `http://localhost:11434`.
- venv app : `<repo>/.venv` (commande serve : `.venv/bin/python -m jobmail serve`).
- Ollama **smart** : démarrer seulement si `:11434` ne répond pas ; ne tuer que si JobMail l'a démarré (marqueur `~/.jobmail/ollama.started-by-jobmail`).
- État runtime : `~/.jobmail/` (pids, marqueur, logs).
- Les scripts bash doivent être paramétrables par env (`JOBMAIL_STATE_DIR`, `OLLAMA_BIN`, `OLLAMA_URL`, `JOBMAIL_REPO`, `JOBMAIL_SERVE_CMD`) pour être testables sans vrais serveurs.
- Fail-loud : si le backend ne monte pas en 30s → MessageBox avec le tail du log + cleanup, jamais de fenêtre blanche silencieuse.

---

### Task 1: Scripts de cycle de vie WSL (`start.sh` / `stop.sh`) + test bash

**Files:**
- Create: `scripts/desktop/start.sh`
- Create: `scripts/desktop/stop.sh`
- Test: `tests/desktop/test_lifecycle.sh`

**Interfaces:**
- Produces: `scripts/desktop/start.sh` (démarre ollama-smart + uvicorn, écrit `$STATE_DIR/{jobmail.pid,ollama.pid,ollama.started-by-jobmail}`) ; `scripts/desktop/stop.sh` (tue uvicorn toujours, ollama seulement si marqueur). Les deux honorent les env vars de Global Constraints. Consommés par `launch.ps1` (Task 2) via `wsl.exe`.

- [ ] **Step 1: Écrire le test bash (échoue car scripts absents)**

Create `tests/desktop/test_lifecycle.sh`:

```bash
#!/usr/bin/env bash
# Teste la logique ollama-smart de start.sh/stop.sh sans vrais serveurs.
# Mocks: faux `curl` (santé ollama pilotée par FAKE_OLLAMA_UP), faux `ollama` (sleep),
# uvicorn remplacé par `sleep` via JOBMAIL_SERVE_CMD.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
FAILED=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILED=1; }

make_env() {
  TMP="$(mktemp -d)"
  BIN="$TMP/bin"; mkdir -p "$BIN"
  STATE="$TMP/state"
  cat > "$BIN/ollama" <<'EOF'
#!/usr/bin/env bash
exec sleep 120
EOF
  cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
# Health check succeeds only when FAKE_OLLAMA_UP=1.
[[ "${FAKE_OLLAMA_UP:-0}" == "1" ]] && exit 0 || exit 7
EOF
  chmod +x "$BIN/ollama" "$BIN/curl"
}

run_start() {
  PATH="$BIN:$PATH" JOBMAIL_STATE_DIR="$STATE" OLLAMA_BIN="$BIN/ollama" \
    OLLAMA_URL="http://localhost:11434" JOBMAIL_REPO="$REPO" \
    JOBMAIL_SERVE_CMD="sleep 120" FAKE_OLLAMA_UP="$1" \
    bash "$REPO/scripts/desktop/start.sh" >/dev/null 2>&1
}
run_stop() {
  PATH="$BIN:$PATH" JOBMAIL_STATE_DIR="$STATE" \
    bash "$REPO/scripts/desktop/stop.sh" >/dev/null 2>&1
}
alive() { local f="$STATE/$1"; [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; }
cleanup() {
  for f in jobmail.pid ollama.pid; do
    [[ -f "$STATE/$f" ]] && kill "$(cat "$STATE/$f")" 2>/dev/null
  done
  rm -rf "$TMP"
}

# Scenario A: ollama DOWN -> JobMail starts it, sets marker, kills both on stop.
make_env
run_start 0
alive jobmail.pid && pass "A: uvicorn started" || fail "A: uvicorn not started"
alive ollama.pid  && pass "A: ollama started"  || fail "A: ollama not started"
[[ -f "$STATE/ollama.started-by-jobmail" ]] && pass "A: marker set" || fail "A: marker missing"
ollama_pid="$(cat "$STATE/ollama.pid")"; jobmail_pid="$(cat "$STATE/jobmail.pid")"
run_stop
kill -0 "$jobmail_pid" 2>/dev/null && fail "A: uvicorn still alive" || pass "A: uvicorn stopped"
kill -0 "$ollama_pid" 2>/dev/null && fail "A: ollama still alive"  || pass "A: ollama stopped"
[[ -f "$STATE/ollama.started-by-jobmail" ]] && fail "A: marker not cleared" || pass "A: marker cleared"
cleanup

# Scenario B: ollama UP -> JobMail must NOT start it, no marker, stop leaves ollama alone.
make_env
"$BIN/ollama" & external_ollama=$!   # simulate an ollama already running elsewhere
run_start 1
alive jobmail.pid && pass "B: uvicorn started" || fail "B: uvicorn not started"
[[ -f "$STATE/ollama.pid" ]] && fail "B: ollama.pid should be absent" || pass "B: no ollama.pid"
[[ -f "$STATE/ollama.started-by-jobmail" ]] && fail "B: marker must be absent" || pass "B: no marker"
jobmail_pid="$(cat "$STATE/jobmail.pid")"
run_stop
kill -0 "$jobmail_pid" 2>/dev/null && fail "B: uvicorn still alive" || pass "B: uvicorn stopped"
kill -0 "$external_ollama" 2>/dev/null && pass "B: external ollama untouched" || fail "B: external ollama killed!"
kill "$external_ollama" 2>/dev/null
cleanup

[[ "$FAILED" == "0" ]] && { echo "ALL PASS"; exit 0; } || { echo "FAILURES"; exit 1; }
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `bash tests/desktop/test_lifecycle.sh`
Expected: FAIL — `start.sh: No such file or directory` (les scripts n'existent pas encore).

- [ ] **Step 3: Écrire `scripts/desktop/start.sh`**

```bash
#!/usr/bin/env bash
# Démarre ollama (smart) + uvicorn pour l'app de bureau JobMail.
set -uo pipefail

REPO_DIR="${JOBMAIL_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
STATE_DIR="${JOBMAIL_STATE_DIR:-$HOME/.jobmail}"
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/ollama/bin/ollama}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
SERVE_CMD="${JOBMAIL_SERVE_CMD:-$REPO_DIR/.venv/bin/python -m jobmail serve}"

mkdir -p "$STATE_DIR"

# 1. Idempotence : tuer un uvicorn JobMail resté d'une session précédente.
if [[ -f "$STATE_DIR/jobmail.pid" ]]; then
  old="$(cat "$STATE_DIR/jobmail.pid")"
  [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null && kill "$old" 2>/dev/null || true
  rm -f "$STATE_DIR/jobmail.pid"
fi

# 2. Ollama smart : démarrer seulement s'il ne répond pas déjà.
if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "ollama déjà actif — on n'y touche pas"
else
  echo "démarrage d'ollama..."
  nohup "$OLLAMA_BIN" serve > "$STATE_DIR/ollama.log" 2>&1 &
  echo $! > "$STATE_DIR/ollama.pid"
  touch "$STATE_DIR/ollama.started-by-jobmail"
fi

# 3. Démarrer uvicorn (jobmail serve) en arrière-plan.
echo "démarrage de jobmail serve..."
cd "$REPO_DIR"
nohup $SERVE_CMD > "$STATE_DIR/jobmail.log" 2>&1 &
echo $! > "$STATE_DIR/jobmail.pid"

echo "started"
```

- [ ] **Step 4: Écrire `scripts/desktop/stop.sh`**

```bash
#!/usr/bin/env bash
# Stoppe uvicorn, et ollama uniquement si JobMail l'a démarré.
set -uo pipefail

STATE_DIR="${JOBMAIL_STATE_DIR:-$HOME/.jobmail}"

_kill_pidfile() {
  local f="$1" pid
  [[ -f "$f" ]] || return 0
  pid="$(cat "$f")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  rm -f "$f"
}

# 1. Toujours stopper uvicorn.
_kill_pidfile "$STATE_DIR/jobmail.pid"

# 2. Stopper ollama seulement si on l'a démarré.
if [[ -f "$STATE_DIR/ollama.started-by-jobmail" ]]; then
  _kill_pidfile "$STATE_DIR/ollama.pid"
  rm -f "$STATE_DIR/ollama.started-by-jobmail"
fi

echo "stopped"
```

- [ ] **Step 5: Rendre exécutable et relancer le test**

Run:
```bash
chmod +x scripts/desktop/start.sh scripts/desktop/stop.sh tests/desktop/test_lifecycle.sh
bash tests/desktop/test_lifecycle.sh
```
Expected: `ALL PASS` (toutes les lignes `PASS:`, exit 0).

- [ ] **Step 6: Commit**

```bash
git add scripts/desktop/start.sh scripts/desktop/stop.sh tests/desktop/test_lifecycle.sh
git commit -m "feat(desktop): scripts WSL start/stop ollama-smart + test bash"
```

---

### Task 2: Orchestrateur Windows (`launch.ps1` + `launch.vbs`)

**Files:**
- Create: `scripts/desktop/windows/launch.ps1`
- Create: `scripts/desktop/windows/launch.vbs`

**Interfaces:**
- Consumes: `scripts/desktop/start.sh` et `stop.sh` (Task 1) via `wsl.exe -d Ubuntu -e bash -lc`.
- Produces: `launch.vbs` (point d'entrée caché lancé par le raccourci, Task 3) qui exécute `launch.ps1` dans le même dossier.

> Cette tâche n'a pas de test automatisé (glu Windows non pilotable depuis WSL). Validation = checklist d'acceptation manuelle de la Task 4.

- [ ] **Step 1: Écrire `scripts/desktop/windows/launch.ps1`**

```powershell
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
    $log = wsl.exe -d $Distro -e bash -lc "tail -n 20 ~/.jobmail/jobmail.log 2>/dev/null"
    wsl.exe -d $Distro -e bash -lc "'$RepoLinux/scripts/desktop/stop.sh'" | Out-Null
    Show-Error "JobMail n'a pas demarre en 30s.`n`n$log"
    return
}

# 4. Ouvrir la fenetre dediee et bloquer jusqu'a sa fermeture.
$win = Open-Window
$win.WaitForExit()

# 5. Tout eteindre.
wsl.exe -d $Distro -e bash -lc "'$RepoLinux/scripts/desktop/stop.sh'" | Out-Null
```

- [ ] **Step 2: Écrire `scripts/desktop/windows/launch.vbs`**

```vbscript
' Lance l'orchestrateur PowerShell en cache (pas de flash de console).
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & dir & "\launch.ps1""", 0, False
```

- [ ] **Step 3: Vérifier la syntaxe PowerShell (parse-only, depuis WSL)**

Run:
```bash
test -f scripts/desktop/windows/launch.ps1 && test -f scripts/desktop/windows/launch.vbs && echo "files OK"
```
Expected: `files OK` (la validation fonctionnelle réelle se fait sur Windows en Task 4).

- [ ] **Step 4: Commit**

```bash
git add scripts/desktop/windows/launch.ps1 scripts/desktop/windows/launch.vbs
git commit -m "feat(desktop): orchestrateur Windows launch.ps1 + launch.vbs"
```

---

### Task 3: Icône + installeur de raccourci (`make_icon.py` + `install.ps1`)

**Files:**
- Create: `scripts/desktop/make_icon.py`
- Create: `scripts/desktop/windows/JobMail.ico` (généré)
- Create: `scripts/desktop/windows/install.ps1`

**Interfaces:**
- Consumes: `launch.ps1`, `launch.vbs` (Task 2).
- Produces: `install.ps1` qui copie `launch.ps1` + `launch.vbs` + `JobMail.ico` vers `%LOCALAPPDATA%\JobMail\` et crée `JobMail.lnk` (Bureau + Menu Démarrer) ciblant `wscript.exe "<dest>\launch.vbs"` avec l'icône.

- [ ] **Step 1: Écrire `scripts/desktop/make_icon.py`**

```python
#!/usr/bin/env python3
"""Génère scripts/desktop/windows/JobMail.ico — icône simple (enveloppe indigo)."""
import sys
from PIL import Image, ImageDraw

def main(out: str) -> None:
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=(79, 70, 229, 255))
    d.rounded_rectangle([56, 84, S - 56, S - 84], radius=16, fill=(255, 255, 255, 255))
    d.line([56, 92, S // 2, 150], fill=(79, 70, 229, 255), width=10)
    d.line([S - 56, 92, S // 2, 150], fill=(79, 70, 229, 255), width=10)
    img.save(out, format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {out}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "JobMail.ico")
```

- [ ] **Step 2: Générer l'icône via un venv jetable (Pillow)**

Run:
```bash
python3 -m venv /tmp/jobmail-icogen
/tmp/jobmail-icogen/bin/pip -q install pillow
/tmp/jobmail-icogen/bin/python scripts/desktop/make_icon.py scripts/desktop/windows/JobMail.ico
rm -rf /tmp/jobmail-icogen
```
Expected: `wrote scripts/desktop/windows/JobMail.ico` et `file scripts/desktop/windows/JobMail.ico` → `MS Windows icon resource`.

- [ ] **Step 3: Vérifier l'icône**

Run: `file scripts/desktop/windows/JobMail.ico`
Expected: contient `MS Windows icon resource` avec plusieurs icônes.

- [ ] **Step 4: Écrire `scripts/desktop/windows/install.ps1`**

```powershell
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
```

- [ ] **Step 5: Commit**

```bash
git add scripts/desktop/make_icon.py scripts/desktop/windows/JobMail.ico scripts/desktop/windows/install.ps1
git commit -m "feat(desktop): icone JobMail.ico + installeur de raccourci install.ps1"
```

---

### Task 4: Documentation + checklist d'acceptation manuelle

**Files:**
- Modify: `README.md` (ajout d'une section « Lancer comme une appli de bureau (Windows) »)

**Interfaces:**
- Consumes: tous les artefacts des Tasks 1-3.
- Produces: documentation d'install/usage + checklist d'acceptation que l'utilisateur exécute sur Windows.

- [ ] **Step 1: Ajouter la section au `README.md`**

Insérer (après la section d'installation/usage existante) :

```markdown
## Lancer comme une appli de bureau (Windows)

JobMail tourne dans WSL mais peut se lancer comme une appli Windows.

**Installer (une seule fois)** — depuis l'Explorateur Windows, aller dans
`\\wsl.localhost\Ubuntu\home\sylvain_ladoire\projects\developpeur\jobmail-assistant\scripts\desktop\windows\`,
clic droit sur `install.ps1` → « Exécuter avec PowerShell ».
Crée un raccourci **JobMail** sur le Bureau et dans le menu Démarrer.

**Utiliser** — double-clic sur l'icône **JobMail** :
1. ollama démarre (seulement s'il ne tourne pas déjà) + le serveur démarre dans WSL ;
2. une fenêtre dédiée s'ouvre sur le dashboard (Edge en mode app, sans barre d'URL) ;
3. **fermer la fenêtre éteint tout** — le serveur, et ollama uniquement si JobMail l'avait démarré.

Re-double-cliquer alors que l'app tourne déjà ouvre simplement une seconde fenêtre.
Si le serveur ne démarre pas en 30 s, une boîte de dialogue affiche les dernières
lignes du log (`~/.jobmail/jobmail.log`).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(desktop): section app de bureau Windows + usage"
```

- [ ] **Step 3: Checklist d'acceptation manuelle (sur Windows, par l'utilisateur)**

À exécuter à la main — c'est la validation finale du launcher :

```
[ ] Lancer install.ps1 → raccourci JobMail présent sur le Bureau + menu Démarrer, avec l'icône.
[ ] (ollama éteint) Double-clic → fenêtre dédiée s'ouvre sur le dashboard, sans barre d'URL.
[ ] Dans WSL : `pgrep -f 'jobmail serve'` non vide ; `curl -sf localhost:11434/api/tags` répond.
[ ] Fermer la fenêtre → dans WSL `pgrep -f 'jobmail serve'` VIDE ; ollama éteint (démarré par JobMail).
[ ] (ollama déjà lancé manuellement) Double-clic → fenêtre s'ouvre. Fermer → ollama TOUJOURS actif (intact).
[ ] App déjà lancée → re-double-clic → 2e fenêtre s'ouvre, pas de 2e serveur (un seul jobmail.pid).
```

---

## Self-Review

- **Couverture spec** : start/stop ollama-smart + pids/marqueur → Task 1 ✓ ; orchestrateur + WaitForExit + déjà-lancé + fail-loud 30s → Task 2 ✓ ; icône + install raccourci Bureau/Menu Démarrer → Task 3 ✓ ; double-clic/fermeture documentés + acceptation → Task 4 ✓. Hors-scope (MSI, tray, pywebview, modif Python) bien exclu.
- **Placeholders** : aucun — tout le code est écrit en entier.
- **Cohérence des types/chemins** : `start.sh`/`stop.sh`, `$STATE_DIR/{jobmail.pid,ollama.pid,ollama.started-by-jobmail}`, `launch.ps1`→`start.sh`/`stop.sh`, `install.ps1`→`launch.vbs`/`launch.ps1`/`JobMail.ico` : noms identiques d'une tâche à l'autre. Env vars cohérentes avec Global Constraints.
