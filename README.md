# JobMail Assistant

[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-D97757?logo=anthropic&logoColor=white)](https://claude.com/claude-code)
[![Coded with Codex](https://img.shields.io/badge/Coded%20with-Codex-111827?logo=openai&logoColor=white)](https://openai.com/codex)
[![Prompts by ChatGPT](https://img.shields.io/badge/Prompts%20by-ChatGPT-10A37F?logo=openai&logoColor=white)](https://chat.openai.com)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-local-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org)
[![Ollama](https://img.shields.io/badge/Ollama-llama3.1%3A8b-000000?logo=ollama&logoColor=white)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local, privacy-first triage of job-recruitment emails.
Reads your mailbox (IMAP or Thunderbird MBOX), filters **locally**, and only sends
**job-related** emails to an LLM (Ollama / Claude / OpenAI) for structured extraction.

**Prompts and feature framing generated with [ChatGPT](https://chat.openai.com);
implementation pair-programmed with [Claude Code](https://claude.com/claude-code)
and [Codex](https://openai.com/codex).**

> **Privacy invariant** — the full mailbox is **never** sent to a cloud API. A 100% local
> keyword filter runs first; only mails that pass it ever reach an LLM. Verified by
> [`tests/test_pipeline_privacy.py`](tests/test_pipeline_privacy.py).

## Features (V1)

- IMAP fetcher (`.env` driven) + Thunderbird MBOX reader with incremental offsets
- Local rule-based filter (FR + EN keywords + your stack: Java/GeoServer/OpenLayers/K8s/PostGIS/Spring/Docker…)
- Pluggable providers: `mock` (default, offline), `ollama` (local), `claude`, `openai`
- Dry-run mode: reads and classifies locally, with no LLM provider instantiation
- Mailbox cleaner: dry-run scan for old Thunderbird/IMAP newsletters, bulk selection by sender, CSV export, then optional move
- SQLite storage (single file, no server)
- HTML dashboard (FastAPI + Jinja2) — list, filter by techno/score/status, mark new/interesting/ignored/replied, open extracted offer links
- CLI: `jobmail fetch | dry-run | watch | extract | serve | seed | classify`

## Architecture

```
IMAP/Thunderbird ──► parser ──► local rules ──► [job_related?] ──► LLM extract ──► SQLite ──► HTML dashboard
                                       │                ▲
                                       └─ "no" ─────────┘ (extractor NEVER called)
```

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

Safety rules:

- No permanent deletion.
- Promotional scans exclude mails containing safety terms such as emploi,
  recrutement, candidature, RH, contrat, facture, banque, impots, securite,
  mot de passe, compte, assurance.
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
- Regex scans launched from the web UI run in the background with live progress:
  scanned mail count, candidate count, current mailbox, elapsed time, then the
  final report is loaded automatically.
- A report is shown before any move, and confirmation checkboxes are required.
- Logs never include the full mail content.

Move actions:

- IMAP source: checked mails are moved to the IMAP folder configured by
  `CLEANER_DELETE_FOLDER` (`ToDelete` by default). This is a quarantine folder,
  not the trash.
- Thunderbird MBOX source: checked mails are moved to the local Thunderbird
  `Trash` file for the same account. JobMail first creates an
  `Inbox.jobmail-backup-YYYYMMDD-HHMMSS` backup, rewrites the Inbox without the
  selected messages, appends the messages to `Trash`, and removes `.msf` index
  files so Thunderbird rebuilds them. Thunderbird must be closed.
- Regex Thunderbird source: all regex results from the dry-run can be moved to
  the local Thunderbird trash in one action. Safety keywords and the age filter
  still apply.
- Parsed jobs source: already extracted job mails can also be moved to the
  Thunderbird trash from `/cleaner/jobs`; only mails linked to ignored offers or
  offers scored 0-3 are proposed. Offers marked `interesting` or `replied` are
  protected.

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

## Tests

```powershell
pytest
pytest -q tests/test_pipeline_privacy.py  # privacy invariants only
```

## Layout

```
jobmail/
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

## Roadmap

- [ ] OpenAI provider (structured outputs)
- [ ] Per-email "why was this kept?" inline matched-keyword viewer
- [ ] CSV / JSON export of offers
- [ ] Notifications Windows (toast) on new high-score offer
- [ ] Crontab via Windows Task Scheduler hint in README

## License

MIT.

---

*Prompts by ChatGPT; built collaboratively with Claude Code and Codex.*
