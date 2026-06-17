# JobMail — App de bureau (launcher Windows + WSL)

**Date** : 2026-06-17
**Statut** : Design validé, prêt pour plan d'implémentation

## Objectif

Permettre de lancer JobMail comme une application Windows standard :

- **Double-clic sur une icône** → l'app démarre (ollama si besoin + uvicorn) et s'ouvre dans une **fenêtre dédiée** (sans barre d'URL navigateur).
- **Fermer la fenêtre** → tout s'éteint proprement (uvicorn, et ollama seulement si JobMail l'avait démarré).

Contrainte structurante : l'app vit **dans WSL** (Ubuntu, Big-Blue), mais le lancement se fait **depuis Windows**. Aucune modification du code Python : c'est une couche *launcher* pure.

## Décisions validées

| Sujet | Décision |
|-------|----------|
| Expérience | Fenêtre app dédiée (Edge `--app`, profil isolé), fermer = tout éteindre. |
| Window tech | Edge `--app` mode (Chromium, déjà présent Win11, rendu fidèle au frontend Vue/Tailwind). Pas de pywebview/WSLg. |
| Ollama | **Smart** : démarre seulement si `:11434` ne répond pas ; ne l'éteint QUE si JobMail l'a démarré (marqueur). |
| Propriétaire du cycle de vie | Le process PowerShell orchestrateur (`launch.ps1`), via `WaitForExit` sur la fenêtre Edge. |

## Faits techniques vérifiés

- `jobmail serve` bind `127.0.0.1:8765` (config par défaut) → **accessible depuis Windows via `http://localhost:8765`** grâce au localhost-forwarding WSL2 (Win11).
- Distro WSL = `Ubuntu` → invocable via `wsl.exe -d Ubuntu bash -lc "…"`.
- Ollama installé user-local : `~/.local/ollama/bin/ollama` (pas dans le PATH par défaut d'un shell non-login → utiliser le chemin complet).
- venv du projet : `~/projects/developpeur/jobmail-assistant/.venv`.

## Architecture

```
Icône Windows (JobMail.lnk, Bureau + Menu Démarrer)
  └─> launch.vbs                    (lance PowerShell caché — pas de flash console)
        └─> launch.ps1              ◄── ORCHESTRATEUR / PROPRIÉTAIRE DU CYCLE DE VIE
              1. Si :8765 répond déjà → ouvrir juste une fenêtre Edge (pas de 2e stack). FIN.
              2. wsl.exe -d Ubuntu  scripts/desktop/start.sh   (ollama smart + uvicorn, en arrière-plan)
              3. Poll http://localhost:8765/ jusqu'à READY (timeout 30s)
                 → si timeout : MessageBox(tail du log) + stop.sh + EXIT
              4. Start-Process msedge --app=http://localhost:8765 --user-data-dir=<profil isolé> -PassThru → $win
              5. $win.WaitForExit()       ◄── bloque tant que la fenêtre est ouverte
              6. wsl.exe -d Ubuntu  scripts/desktop/stop.sh    (kill propre)
```

## Composants

### Côté WSL — `scripts/desktop/`

Dossier d'état runtime : `~/.jobmail/` (pids + marqueurs + logs).

**`start.sh`**
1. Idempotence : si un uvicorn JobMail zombie tourne (PID file stale ou `pgrep -f 'jobmail serve'`), le tuer d'abord.
2. Ollama smart :
   - Si `curl -sf http://localhost:11434/api/tags` répond → ne rien faire.
   - Sinon : `nohup ~/.local/ollama/bin/ollama serve > ~/.jobmail/ollama.log 2>&1 &`, écrire `~/.jobmail/ollama.pid`, **toucher `~/.jobmail/ollama.started-by-jobmail`**.
3. Uvicorn : `cd <repo> && nohup .venv/bin/python -m jobmail serve > ~/.jobmail/jobmail.log 2>&1 &`, écrire `~/.jobmail/jobmail.pid`.
4. Sortir immédiatement (les process restent en arrière-plan, détachés du shell `wsl.exe`).

**`stop.sh`**
1. Tuer le process uvicorn (`~/.jobmail/jobmail.pid`, fallback `pkill -f 'jobmail serve'`).
2. Si `~/.jobmail/ollama.started-by-jobmail` existe → tuer `~/.jobmail/ollama.pid`, puis retirer le marqueur.
3. Nettoyer les PID files.

### Côté Windows — `scripts/desktop/windows/`

**`launch.ps1`** : l'orchestrateur décrit ci-dessus.
- Profil Edge isolé : `%LOCALAPPDATA%\JobMail\edge-profile` (force un process Edge dédié → `WaitForExit` fiable, fenêtre propre).
- Args Edge : `--app=http://localhost:8765 --user-data-dir=… --window-size=1400,900` (taille initiale ; pas de `--new-window` nécessaire avec profil dédié).
- Le `wsl.exe` est invoqué avec le chemin du repo en dur (résolu à l'install ou paramétré en tête de script).

**`launch.vbs`** : ~3 lignes, `WScript.Shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -File launch.ps1", 0, False` (fenêtre 0 = cachée).

**`install.ps1`** (à lancer une fois) :
- Crée `%LOCALAPPDATA%\JobMail\`, y copie `launch.ps1`, `launch.vbs`, `JobMail.ico`.
- Détecte le chemin du repo via `wsl.exe -d Ubuntu wslpath` ou le code en dur, et l'injecte dans `launch.ps1`.
- Crée le raccourci `JobMail.lnk` (cible = `wscript.exe …\launch.vbs`, icône = `JobMail.ico`) sur le Bureau **et** dans le Menu Démarrer.

**`JobMail.ico`** : icône générée (depuis le favicon du frontend si présent, sinon enveloppe 📬). Multi-résolutions (16/32/48/256).

## Cycle de vie & cas limites

| Cas | Comportement |
|-----|--------------|
| Fermer la fenêtre Edge | `WaitForExit` retourne → `stop.sh` → uvicorn tué, ollama tué si marqueur. **Cœur de la demande.** |
| Double-clic alors que déjà lancé | `:8765` répond → on ouvre juste une 2e fenêtre Edge, pas de 2e stack. |
| Backend pas prêt en 30s | MessageBox avec le tail de `~/.jobmail/jobmail.log` + `stop.sh` + exit. Fail-loud, pas de fenêtre blanche. |
| Ollama utilisé ailleurs (evatosorus…) | Smart : pas de marqueur → jamais tué. |
| PowerShell tué brutalement (Task Manager) | Orphelins WSL possibles → le prochain `start.sh` les nettoie (idempotent). |
| Edge absent | Win11 l'a par défaut ; sinon fallback Chrome si présent, sinon MessageBox d'erreur. |

## Tests

- **Bash** : test de la logique marqueur ollama de `start.sh`/`stop.sh` (ollama démarré → marqueur posé → `stop.sh` le tue et retire le marqueur ; ollama déjà up → pas de marqueur → `stop.sh` ne touche pas ollama ; uvicorn toujours tué). Exécutable via un petit script de test bash avec un faux `ollama`/`curl` mockés sur le PATH.
- **Manuel (checklist d'acceptation)** : `install.ps1` → double-clic icône → fenêtre s'ouvre sur le dashboard → fermer → `wsl pgrep -f 'jobmail serve'` vide → ollama état conforme (tué si démarré par JobMail, intact sinon).

## Hors scope (YAGNI)

- Pas de packaging MSI/installer signé.
- Pas de tray icon / auto-start au boot.
- Pas de pywebview/Electron/Tauri.
- Pas de modification du code Python de l'app.
