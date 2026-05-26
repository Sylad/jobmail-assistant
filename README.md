# JobMail Assistant

[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-D97757?logo=anthropic&logoColor=white)](https://claude.com/claude-code)
[![Coded with Codex](https://img.shields.io/badge/Coded%20with-Codex-111827?logo=openai&logoColor=white)](https://openai.com/codex)
[![Prompts by ChatGPT](https://img.shields.io/badge/Prompts%20by-ChatGPT-10A37F?logo=openai&logoColor=white)](https://chat.openai.com)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3-42B883?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)](https://vite.dev)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![shadcn-vue style](https://img.shields.io/badge/UI-shadcn--vue%20style-111827?logo=shadcnui&logoColor=white)](https://www.shadcn-vue.com)
[![Reka UI](https://img.shields.io/badge/Reka%20UI-accessible%20primitives-7C3AED)](https://reka-ui.com)
[![SQLite](https://img.shields.io/badge/SQLite-local-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org)
[![Ollama](https://img.shields.io/badge/Ollama-llama3.1%3A8b-000000?logo=ollama&logoColor=white)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local, privacy-first triage of job-recruitment emails.
Reads your mailbox (IMAP or Thunderbird MBOX), filters **locally**, and only sends
**job-related** emails to an LLM (Ollama / Claude / OpenAI) for structured extraction.

**Prompts and feature framing generated with [ChatGPT](https://chat.openai.com);
implementation pair-programmed with [Claude Code](https://claude.com/claude-code)
and [OpenAI Codex](https://openai.com/codex).**

> **Privacy invariant** — the full mailbox is **never** sent to a cloud API. A 100% local
> keyword filter runs first; only mails that pass it ever reach an LLM. Verified by
> [`tests/test_pipeline_privacy.py`](tests/test_pipeline_privacy.py).

## What it does

JobMail Assistant has two complementary workflows:

1. **Job-offer triage** — reads mails from IMAP or Thunderbird MBOX, classifies
   them locally, sends only job-related mails to the selected LLM provider, then
   stores structured offers in SQLite.
2. **Mailbox cleaner** — scans old newsletters/promotional mails in dry-run,
   displays a reviewable report, then moves explicitly confirmed selections to a
   quarantine/trash folder without permanent deletion.

Main capabilities:

- IMAP fetcher (`.env` driven) and Thunderbird MBOX reader with incremental offsets.
- Local rule-based job filter (FR + EN keywords + target stack:
  Java/GeoServer/OpenLayers/K8s/PostGIS/Spring/Docker…).
- Pluggable LLM providers: `mock` (default, offline), `ollama` (local), `claude`, `openai`.
- Dry-run mode: reads and classifies locally, with no LLM provider instantiation.
- SQLite storage: a single local DB file, no external server.
- FastAPI/Jinja dashboard with Vue 3 islands for interactive cleaner workflows.
- CLI: `jobmail fetch | dry-run | watch | extract | serve | seed | classify`.

## How it works

```
IMAP / Thunderbird MBOX
          │
          ▼
mail parser + body normalizer
          │
          ▼
local privacy filter ──────► not job-related ──────► stored locally, no LLM call
          │
          ▼
job-related only
          │
          ▼
LLM extractor (mock / Ollama / Claude / OpenAI)
          │
          ▼
SQLite offers + FastAPI dashboard
```

Cleaner actions follow a separate path:

```
Thunderbird MBOX / IMAP / parsed jobs
          │
          ▼
dry-run scan with age, regex and safety checks
          │
          ▼
review report + selected candidates
          │
          ▼
explicit confirmation
          │
          ▼
move to Thunderbird Trash or IMAP ToDelete, never permanent delete
```

## Web UI

- `/` shows extracted job offers, filters by status/technology/sender/score, and
  lets offers be marked `new`, `interesting`, `ignored`, or `replied`.
- `/offers/{id}` opens the extracted offer details and links back to the original
  job URL when one was found in the mail.
- `/cleaner` scans old promotional mails from Thunderbird MBOX or IMAP.
- `/cleaner/jobs` lists already parsed low-value job mails that can be moved out
  after review.
- `/cleaner/duplicates` detects Orange-to-Gmail forwarded duplicates by
  `Message-Id` and proposes only the redundant Orange copies.

The dashboard is server-rendered with FastAPI/Jinja for simple pages. The cleaner
uses Vue 3 + TypeScript islands for the interactive parts: progressive scan
feedback, cancellation, regex rule rows, move progress, and candidate selection.

## Install — Windows

Requires **Python 3.12+**. Open *PowerShell* in the project directory.

```powershell
# 1. virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. base install (mock extractor only, no API needed)
pip install -e .

# 3. optional providers
pip install -e ".[claude]"   # Anthropic Claude
pip install -e ".[openai]"   # OpenAI (stub for now)
# Ollama needs no extra Python deps — only the Ollama server running on localhost.

# 4. dev tools (tests, lint)
pip install -e ".[dev]"
```

If `Activate.ps1` is blocked:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Configuration

Copy `.env.example` → `.env` and fill what you need.

```dotenv
# Leave IMAP_HOST empty to disable IMAP and use mock data
IMAP_HOST=imap.example.com
IMAP_USER=you@example.com
IMAP_PASSWORD=app-specific-password   # Gmail: app password; Outlook: app password
IMAP_FOLDER=INBOX
IMAP_FETCH_LIMIT=50

CLEANER_MIN_AGE_DAYS=7               # default age threshold for /cleaner
CLEANER_MAX_MAILS=250                # scan cap for safety/latency
CLEANER_DELETE_FOLDER=ToDelete       # IMAP folder used by the move action
CLEANER_MBOX_GLOBS="/mnt/c/Users/Sylvain Ladoire/AppData/Roaming/Thunderbird/Profiles/*.default*/Mail/pop.*/Inbox"

LLM_PROVIDER=mock                     # mock | ollama | claude | openai
DRY_RUN=false                         # true = classify only, no LLM calls
ANTHROPIC_API_KEY=sk-ant-...          # if LLM_PROVIDER=claude
ANTHROPIC_MODEL=claude-sonnet-4-6
OLLAMA_MODEL=llama3.1                 # if LLM_PROVIDER=ollama
OPENAI_API_KEY=sk-...                 # if LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4o-mini
TARGET_PROFILE="Java senior, GeoServer, OpenLayers, Kubernetes, PostGIS, Spring, Docker"
```

> **No `.env` ?** The app starts on mock data — perfect for demoing the UI without
> exposing any credentials.

## Run

```powershell
# 1. seed the DB with 10 mock emails (no IMAP, no LLM call) — instant demo
python -m jobmail seed

# 2. open the dashboard
python -m jobmail serve
# → http://127.0.0.1:8765/
```

## Frontend assets

The dashboard is server-rendered with Jinja, and the Mailbox cleaner uses a
small Vue 3/Vite/TypeScript island for client-side scan progress, cancellation,
regex rule rows, and selection helpers. The frontend is structured with
composables plus shadcn-style primitives on top of Tailwind CSS, Reka UI,
class-variance-authority, and tailwind-merge.

```bash
cd frontend
npm install
npm run typecheck
npm run build
```

The build writes `jobmail/web/static/assets/cleaner.js` and
`jobmail/web/static/assets/cleaner.css`, which are committed so the local Python
server can run without a separate Vite dev server.

Once configured:

```powershell
# Fetch from IMAP, filter locally, extract via the configured provider
python -m jobmail fetch

# Read and classify only; never instantiates or calls an LLM provider
python -m jobmail fetch --dry-run
python -m jobmail dry-run

# Re-classify cached emails after editing rules.py (no LLM call)
python -m jobmail classify
```

## Mailbox cleaner

Open `/cleaner` in the dashboard to scan old promotional/newsletter mails from
Thunderbird POP3 MBOX files, IMAP, or already parsed job mails. The primary
action is always a dry-run: it reports scanned mails, candidates, top senders,
and the candidate list with reasons.

Scan modes:

- **Thunderbird MBOX**: broad promotional/newsletter detection on local MBOX files.
- **Regex Thunderbird**: explicit sender/subject regex rules for large cleanup passes.
- **Jobs deja parses**: already extracted job mails linked to ignored or low-score offers.
- **Doublons Orange/Gmail**: duplicate detection by `Message-Id` where Orange copies
  also exist in Gmail.
- **IMAP**: old promotional mails through the configured IMAP account.

Safety rules:

- No permanent deletion.
- Promotional scans exclude mails containing `facture`. Other account/security/job
  notifications can be handled by explicit sender/subject regex rules.
- Candidates are selected by default, but can be included/excluded in bulk by
  sender from the "Top expediteurs" table. Excluded senders are visibly marked.
- Thunderbird scans support a "skip first N mails" offset plus a "scan next
  batch" button, so large MBOX files can be processed in windows instead of
  rescanning the same first messages every time.
- Regex scans can match the full Thunderbird mailbox with several readable
  sender/subject rules. Inside a rule, every filled field must match; rules are
  combined as a global OR. Use `0` as max-mails for an unbounded pass. Regex
  moves replay the same rules after the dry-run and move every matching result
  in one Thunderbird rewrite.
- Scans launched from the web UI run in the background with live Vue-powered
  progress: scanned mail count, candidate count, current mailbox, elapsed time,
  cancellation button, then the final report is loaded automatically.
- Regex move actions reuse the completed scan result shown in the UI, so the
  mailbox is not rescanned before moving candidates to Thunderbird trash.
- Regex move actions also run with live progress while the Thunderbird MBOX is
  backed up and rewritten.
- Regex rules are saved locally to `data/cleaner-regex-rules.json` whenever a
  regex scan/export/move is launched, then reloaded on the next `/cleaner` visit.
- A report is shown before any move, and confirmation checkboxes are required.
- Logs never include the full mail content.

Progress and cancellation:

- All web scans run through background jobs and return live Vue progress.
- Scan jobs can be cancelled from the UI.
- Regex move actions also run with live progress and can be cancelled between
  mailbox rewrite steps.
- Long Thunderbird scans can use `max-mails = 0` for an unbounded pass, or a
  finite max plus `skip first N mails` to process the mailbox in windows.

Move actions:

- IMAP source: checked mails are moved to the IMAP folder configured by
  `CLEANER_DELETE_FOLDER` (`ToDelete` by default). This is a quarantine folder,
  not the trash.
- Thunderbird MBOX source: checked mails are moved to the local Thunderbird
  `Trash` file for the same account. JobMail first creates a `.mbox` backup in
  `<profile>/jobmail-backups/` outside Thunderbird's `Mail/<account>` folders,
  rewrites the Inbox without the selected messages, appends the messages to
  `Trash`, and removes `.msf` index files so Thunderbird rebuilds them.
  Thunderbird must be closed.
- Regex Thunderbird source: all regex results from the dry-run can be moved to
  the local Thunderbird trash in one action. Safety keywords and the age filter
  still apply.
- Parsed jobs source: already extracted job mails can also be moved to the
  Thunderbird trash from `/cleaner/jobs`; only mails linked to ignored offers or
  offers scored 0-3 are proposed. Offers marked `interesting` or `replied` are
  protected.

Known operational trade-offs:

- Local Thunderbird moves rewrite MBOX files, so Thunderbird must be closed.
- Backups are created before rewriting and are cleaned only by explicit action.
- The cleaner is intentionally conservative around permanent deletion: it moves
  messages to Trash/ToDelete so the user keeps a recovery path.

## Thunderbird

Thunderbird stores INBOX as an MBOX file at:
`%APPDATA%\Thunderbird\Profiles\<id>\Mail\<server>\Inbox` for POP accounts, or
`%APPDATA%\Thunderbird\Profiles\<id>\ImapMail\<server>\INBOX` for IMAP accounts.

Use the repeatable `--mbox` flag for ingestion:

```powershell
python -m jobmail fetch --mbox "C:\Users\Sylvain Ladoire\AppData\Roaming\Thunderbird\Profiles\<id>\Mail\pop.gmail.com\Inbox" --since-days 90
python -m jobmail watch --mbox "C:\Users\Sylvain Ladoire\AppData\Roaming\Thunderbird\Profiles\<id>\Mail\pop.gmail.com\Inbox"
```

For the web cleaner, configure `CLEANER_MBOX_GLOBS` in `.env`.

Operational notes:

- Close Thunderbird before moving local MBOX messages. On Windows/WSL, verify
  with `powershell.exe -NoProfile -Command "Get-Process thunderbird -ErrorAction SilentlyContinue"`.
- Never create backups directly inside Thunderbird `Mail/<account>` folders.
  Extensionless files there are displayed by Thunderbird as mail folders. JobMail
  stores cleaner backups under `<profile>/jobmail-backups/` instead.
- MBOX files can be several GB. Prefer same-volume hardlinks/moves for backups
  and avoid cross-filesystem copies unless explicitly needed.
- Backups are not deleted automatically in the background. The cleaner page
  shows how many JobMail backups exist under `<profile>/jobmail-backups/`, how
  much space they use, and exposes an explicit confirmed cleanup action for
  backups older than `CLEANER_BACKUP_RETENTION_DAYS` days (`7` by default).
- If an interrupted local move leaves `.Inbox.jobmail-tmp-*` files inside
  Thunderbird `Mail/<account>`, the cleaner page shows them and can move them
  out of the profile after explicit confirmation while Thunderbird is closed.

## Tests

```powershell
pytest
pytest -q tests/test_pipeline_privacy.py  # privacy invariants only
cd frontend
npm run build                            # includes vue-tsc typecheck
```

## Layout

```
jobmail/
├── frontend/        # Vue 3 + TypeScript + Vite cleaner island
├── config.py        # pydantic-settings → .env
├── models.py        # dataclasses Offer/Email/Status
├── db.py            # SQLite schema + helpers
├── pipeline.py      # fetch → filter → extract → store
├── mail/            # IMAP + Thunderbird + parser
├── filtering/       # local keyword rules (privacy-first)
├── extraction/      # LLMProvider + mock/local/cloud providers
├── web/             # FastAPI + Jinja2 dashboard
└── cli.py           # entry-point
```

## Contributors

- [Sylad](https://github.com/Sylad) — project owner, product direction, real-world mailbox workflows.
- [Claude Code](https://claude.com/claude-code) — implementation assistance and iterative coding sessions.
- [OpenAI Codex](https://openai.com/codex) — implementation assistance, frontend hardening, tests, and repository maintenance.

GitHub's automatic Contributors panel is commit-account based; this README keeps
the human/AI collaboration credits explicit even when automated commit attribution
does not expose every assistant as a separate GitHub account.

## Roadmap

- [ ] OpenAI provider (structured outputs)
- [ ] Per-email "why was this kept?" inline matched-keyword viewer
- [ ] CSV / JSON export of offers
- [ ] Notifications Windows (toast) on new high-score offer
- [ ] Crontab via Windows Task Scheduler hint in README

## License

MIT.

---

*Prompts by ChatGPT; built collaboratively with Claude Code and OpenAI Codex.*
