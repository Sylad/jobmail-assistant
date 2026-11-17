# Mise à jour mensuelle des technos — novembre 2026 (L18)

Date : 2026-11-17. Règle suivie : versions mineures et correctifs appliqués,
versions majeures proposées à part sans être appliquées. Le modèle Ollama
(`llama3.1:8b`) n'est pas touché.

## Python (venv, `pip install -U` avec `soupsieve<3` et `websockets<17`)

| Paquet | Avant | Après |
|---|---|---|
| fastapi | 0.136.3 | 0.163.1 |
| starlette (via fastapi) | 1.1.0 | 1.10.0 |
| uvicorn[standard] | 0.48.0 | 0.54.0 |
| Jinja2 / MarkupSafe | 3.1.6 / 3.0.3 | 3.1.6 / 3.0.4 |
| pydantic / pydantic-core | 2.13.4 / 2.46.4 | 2.14.3 / 2.50.4 |
| pydantic-settings | 2.14.1 | 2.16.3 |
| python-multipart | 0.0.29 | 0.0.34 |
| imap-tools | 1.13.0 | 1.16.0 |
| beautifulsoup4 / soupsieve | 4.14.3 / 2.8.4 | 4.15.0 / 2.10 |
| anyio | 4.13.0 | 4.16.0 |
| certifi | 2026.5.20 | 2026.10.23 |
| pytest / pytest-cov / coverage | 9.0.3 / 7.1.0 / 7.14.0 | 9.2.0 / 7.1.0 / 7.17.3 |
| ruff | 0.15.14 | 0.17.5 |
| autres (click, idna, httptools, uvloop, watchfiles, websockets 16.0 → 16.1.1…) | | correctifs |

Nouvelle dépendance transitive : `opentelemetry-api` 1.45.2, tirée par fastapi.

`pyproject.toml` : planchers relevés pour que toute installation neuve reçoive
les correctifs de sécurité — `fastapi>=0.163`, `starlette>=1.3.1` (dépendance
de FastAPI, déclarée pour son plancher), `python-multipart>=0.0.31`,
`pydantic-settings>=2.14.2`.

## Frontend (`frontend/`, `npm update` dans les plages `^`)

vue 3.5.34 → 3.5.45, vite 6.4.2 → 6.4.6, @lucide/vue 1.16 → 1.74, reka-ui
2.9.8 → 2.11.0, tailwindcss et @tailwindcss/vite 4.3.0 → 4.3.5,
tailwind-merge 3.6 → 3.7, vue-tsc 3.3.2 → 3.3.14 ; transitives postcss
8.5.15 → 8.5.33, nanoid 3.3.12 → 3.3.20. Bundle `jobmail/web/static/assets/`
recompilé.

## Audits de sécurité

| | Avant | Après |
|---|---|---|
| `pip-audit` (venv) | 21 avis sur 6 paquets : anyio, certifi, pydantic-settings, python-multipart, soupsieve, starlette | 3 avis sur soupsieve seul (corrigés uniquement en 3.0.2 / 4.0.0, majeures) |
| `npm audit` (frontend) | 6 vulnérabilités élevées : vite, vue, @vue/server-renderer, postcss, nanoid, source-map-js | 0 |

## Régressions

Aucune trouvée.

- `pytest` : 217 tests verts avant et après (tests JS `node --test` compris).
- `ruff check .` : propre avant et après. `ruff format --check` signale
  35 fichiers avec ruff 0.15.14 comme avec 0.17.5 : écart antérieur, non
  imposé par le dépôt, inchangé.
- `vue-tsc --noEmit` et `vite build` : verts.
- Écran `/cleaner` sur une instance de démonstration vide : capture pleine page
  à 1440 px avec l'ancien bundle puis avec le nouveau, **identiques au pixel**,
  console sans erreur ni avertissement.

## Majeures proposées (non appliquées)

| Paquet | Actuel → disponible | Pourquoi | Risque |
|---|---|---|---|
| soupsieve (via beautifulsoup4) | 2.10 → 4.1.1 | 3 avis ouverts (CVE-2026-126190/126191/126193) | Faible exposition : le code n'utilise pas de sélecteurs CSS (`.select()` absent de `jobmail/`). À faire en lot à part, avec `pip-audit` comme critère. |
| websockets (via uvicorn[standard]) | 16.1.1 → 17.4 | suivi de version | L'app n'a pas de route websocket. |
| vite | 6.4.6 → 8.3.8 | deux majeures de retard | Configuration de build à revoir ; à faire avec @vitejs/plugin-vue. |
| @vitejs/plugin-vue | 5.2.4 → 6.0.11 | suit vite | idem. |
| typescript | 6.0.3 → 7.0.2 | nouvelle majeure | Compatibilité vue-tsc à vérifier. |
| pip (outil du venv) | 24.0 → 26.3 | outil, pas une dépendance du projet | Aucun pour le code. |

## Veille (semaine 2026-S47)

Rien qui nous touche : les articles retenus parlent de Python, Playwright ou
Claude Code en général (bibliothèques et projets tiers, quota des sous-agents),
aucun ne concerne une version, une faille ou une dépréciation de FastAPI,
Jinja2, uvicorn, pydantic, imap-tools, beautifulsoup4, pytest, Vue ou Vite.

## Après fusion

Le venv de l'instance locale (`http://localhost:8765`) n'est pas mis à jour par
ce lot : y lancer `.venv/bin/pip install -U -e ".[dev]" "soupsieve<3" "websockets<17"`
puis relancer `jobmail serve`.
