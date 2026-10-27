# jobmail-assistant

## Plan, sessions et revue UX (cadence)

Le reste à faire vit dans `.cadence/raf.yaml`, tenu par `raf`
([cadence](https://github.com/Sylad/cadence)) : chaque commit cite son lot dans le
message (`fix(L4): …`, `L2/t1`), `raf now` dit la suite, `raf check` repère les
écarts. Début et fin de session : skills `/cadence:session-start` et
`/cadence:session-close`.

**Revue UX obligatoire** (règle de Sylvain du 2026-09-28, tous les projets perso) : toute nouvelle
page ou modification d'écran est un lot `--visible`, revu par l'agent `cadence:ux-reviewer` (captures
1440 et 390 px, écarts fondés sur une règle nommée ou une mesure) avant `raf done`. Le verdict
s'enregistre avec `raf ux <lot> "…"`, sinon `raf done` refuse. Les lots « Revue UX — … » planifient
la revue de chaque écran existant ; les écarts trouvés deviennent des sous-tâches du lot.

## Pages Nouveautés et Plan de travail (signature commune des apps)

**Nouveautés** (`/nouveautes`, L6) : les entrées vivent dans `docs/nouveautes/*.md` (captures dans
`docs/nouveautes/captures/`, créées par `cadence news new <lot>`). Après tout ajout ou modification
d'une entrée, lancer `scripts/build-news.sh` (= `cadence news build` vers
`jobmail/web/static/nouveautes-data/`, sans la page `index.html` de cadence) et **commiter le
résultat** : l'application lit ce JSON à chaque requête et tourne sans cadence après un `git clone`.
`pytest` échoue si le JSON versionné ne suit plus `docs/nouveautes/`. Le corps HTML de cadence est
refiltré par une liste blanche (`jobmail/web/news.py`). Pastille, « Nouveau », séparateur « Déjà vu »,
« Copier le lien », capture agrandie : `jobmail/web/static/news-core.js` (logique pure, testée par
`node --test tests/js/*.test.mjs`, aussi lancé par pytest) et `news.js` (branchement DOM), en JavaScript simple
sans build. Mémoire dans `localStorage`, clé `jobmail.news.seen-v1`.

**Plan de travail** (`/plan-de-travail`, L7) : lu à chaque requête dans `.cadence/raf.yaml` par
`jobmail/web/plan_public.py`, liste blanche seulement (titre PUBLIC, état, date de livraison,
décompte des étapes non abandonnées ; l'identifiant n'est qu'un id d'élément). Un lot n'apparaît que
s'il est `visible: true`, non abandonné, et a un titre public : son champ `public:` (une ligne, en
français pour l'utilisateur, ≤ 80 caractères, sans « / », nom de fichier, identifiant de lot ni sujet
de sécurité), sinon — lot livré seulement — le titre de son entrée Nouveautés ; les lots « Revue … »
exigent un `public:`. **Tout nouveau lot visible reçoit un `public:`** (à faire valider par Sylvain).
Groupes : En cours, Prévu, Récemment livré (8 derniers). `tests/test_plan_web.py` prouve qu'aucune
note, verdict, raison ni titre brut n'est rendu (plan synthétique ET vrai plan) et échoue sur un
`public:` non conforme du vrai plan.

**Captures** : JAMAIS de vrai mail, expéditeur, entreprise ou offre (dépôt public). Les prendre sur
une instance de démonstration VIDE : variables `DB_PATH`, `CLEANER_REGEX_RULES_PATH`,
`CLEANER_MBOX_GLOBS` vers `~/projects/developpeur/tmp/jobmail-demo/`, `IMAP_*` vides, lancée depuis
ce dossier (pour ne pas lire le `.env` du dépôt) avec uvicorn sur un autre port que 8765 :

```bash
mkdir -p ~/projects/developpeur/tmp/jobmail-demo && cd ~/projects/developpeur/tmp/jobmail-demo && \
DB_PATH=$PWD/jobmail.db CLEANER_REGEX_RULES_PATH=$PWD/rules.json CLEANER_MBOX_GLOBS=$PWD/none/Inbox \
IMAP_HOST= IMAP_USER= IMAP_PASSWORD= LLM_PROVIDER=mock \
~/projects/developpeur/jobmail-assistant/.venv/bin/python -m uvicorn jobmail.web.app:app \
  --app-dir ~/projects/developpeur/jobmail-assistant --host 127.0.0.1 --port 8799
```

Pour montrer des entrées synthétiques (jamais commitées) sans toucher au dépôt, ajouter
`JOBMAIL_NEWS_DATA_DIR=<dossier>` : un dossier compilé par
`cadence news build --dir <sources synthétiques> -o <dossier>` (servi sous `/static/nouveautes-data/`).

**Tests et vie privée** : `tests/conftest.py` pose ces mêmes variables vers un dossier temporaire
AVANT l'import de l'application (`jobmail.web.app` crée l'app à l'import) : la suite ne touche
jamais `data/jobmail.db` ni le profil Thunderbird.

## Spécificités (déplacées du CLAUDE.md du dossier parent le 2026-10-27)

Local WSL Big-Blue.

**Outil de triage privacy-first des mails de recrutement** (rch emploi Sylvain 2026). Tourne en local — la data source est Thunderbird POP3 sur disque Windows.

- Path projet : `~/projects/developpeur/jobmail-assistant/`
- Repo : https://github.com/Sylad/jobmail-assistant
- Stack : Python 3.12 venv local, FastAPI + Jinja2, SQLite stdlib, Ollama Big-Blue (llama3.1:8b, RTX 5090 32 Go)
- 4 CLI commands découplées : `fetch` (batch incrémental), `watch` (polling 30s + fetch), `extract` (LLM-only rerun), `classify` (rules-only)
- Dashboard : http://localhost:8765/ (FastAPI/uvicorn, banner live `/proc` detection + barre progression)
- MBOX sources : 5 comptes POP3 Thunderbird via `/mnt/c/Users/Sylvain Ladoire/AppData/Roaming/Thunderbird/Profiles/5f0p9ce2.default-esr/Mail/pop.*/Inbox` — cf [[thunderbird_mbox_paths_pop3]]
- Mailbox cleaner `/cleaner` : scan dry-run obligatoire avant action, rapport + top expéditeurs + CSV, candidats cochés par défaut, include/exclude bulk par expéditeur avec état visuel Inclus/Partiel/Exclu.
- Cleaner UI 2026-05-27 : ne plus multiplier les boutons de scan. Le parcours voulu est un flux unique : bouton `Scanner le nettoyage`, puis phases `Pubs anciennes` → `Règles regex` → `Jobs cleanup` → `Doublons`. Le bouton d'action principal doit être visible avant les gros tableaux et déplacer toutes les phases sélectionnées, pas seulement le rapport actif.
- Déplacement multi-phases : dédupliquer par UID avant envoi au backend. Conserver les sélections/exclusions par phase. La progression doit compter `traités`, `déplacés`, `ignorés` ; les mails `parsed_jobs` introuvables dans les MBOX après une phase précédente sont probablement déjà déplacés et doivent apparaître comme ignorés/déjà traités, pas comme une barre bloquée.
- Actions cleaner : IMAP → dossier `ToDelete` (quarantaine, pas trash) ; Thunderbird MBOX → `Trash` local du même compte avec backup `.mbox` dans `<profile>/jobmail-backups/` hors des dossiers `Mail/<compte>`, rewrite Inbox, append Trash, suppression `.msf`, Thunderbird fermé requis.
- Incident appris 2026-05-26 : ne JAMAIS créer de backup directement dans `Mail/<compte>` (`Inbox.jobmail-backup-*` extensionless). Thunderbird les affiche comme des dossiers et peut déclencher une erreur d'enregistrement. Si cela réapparaît : fermer Thunderbird, vérifier `Get-Process thunderbird`, puis déplacer les fichiers hors `Mail/`, ne pas supprimer sans accord explicite.
- Gros MBOX Windows/WSL : éviter les copies cross-filesystem inutiles (plusieurs Go). Préférer un hardlink/copie sur le même volume Windows ou un déplacement atomique si l'on sort des backups du profil.
- Depuis Codex Desktop, pour relancer `http://localhost:8765`, `Start-Process -WindowStyle Hidden wsl.exe` avec une seule chaîne `bash -lc "cd ... && .venv/bin/python -m jobmail serve ..."` est plus fiable que `nohup`/`setsid` lancés depuis un shell qui se ferme.
- Source cleaner `parsed_jobs` : déplace en corbeille Thunderbird les mails de jobs déjà extraits ; offres `interesting` protégées.
- Fiches offres : extraire les liens du HTML/texte stocké et afficher bouton `Voir l'offre` quand un lien exploitable existe.
- Ne jamais supprimer définitivement les mails ; ne jamais toucher aux MBOX sans confirmation UI explicite + backup.
- Tests snapshot après cleaner/job links : 54 tests pytest + `ruff check .`.

**Why local et pas K8s** : POP3 mails sur disque local Windows, pas accessibles depuis le cluster dark-blue. Voir [[feedback_data_layer_decides_deploy_target]].

**Patterns reusable extraits** :
- [[incremental_append_only_reader_pattern]] — table `mbox_state(path, last_offset, last_size)` + Compact detect
- [[privacy_two_layer_llm_filter_pattern]] — filtre rules local AVANT LLM, invariant testé SpyExtractor
- [[live_job_status_ui_pattern]] — process detection /proc + phase + progress bar + meta-refresh
- [[python_mailbox_mbox_avoid_custom_parser]] — stdlib mbox.mbox build TOC plein → custom parser
- [[wsl2_inotify_9p_unreliable]] — polling stat() pour les changes sur /mnt/c
- [[ollama_local_user_install_wsl]] — install user-local sans sudo
- [[wsl2_lan_port_exposition_recipe]] — exposer un service WSL au LAN (4 étapes)
- [[llm_thinking_model_batch_pitfall]] — pourquoi llama3.1 et pas qwen3 pour batch extraction
- [[big_blue_gpu_rtx4080_super]] — la GPU dispo (RTX 5090 32 Go depuis 2026-08-12, le fichier a gardé son ancien nom)
- État snapshot : [[jobmail_assistant_state_2026_05_26]]
