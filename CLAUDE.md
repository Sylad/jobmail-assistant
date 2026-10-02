# jobmail-assistant

## Plan, sessions et revue UX (cadence)

Le reste à faire vit dans `docs/plan/raf.yaml`, tenu par `raf`
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
`node --test tests/js/`, aussi lancé par pytest) et `news.js` (branchement DOM), en JavaScript simple
sans build. Mémoire dans `localStorage`, clé `jobmail.news.seen-v1`.

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

**Tests et vie privée** : `tests/conftest.py` pose ces mêmes variables vers un dossier temporaire
AVANT l'import de l'application (`jobmail.web.app` crée l'app à l'import) : la suite ne touche
jamais `data/jobmail.db` ni le profil Thunderbird.

