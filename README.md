# JobMail Assistant

Local, privacy-first triage of job-recruitment emails.
Reads your mailbox (IMAP or Thunderbird MBOX), filters **locally**, and only sends
**job-related** emails to an LLM (Ollama / Claude / OpenAI) for structured extraction.

> **Privacy invariant** — the full mailbox is **never** sent to a cloud API. A 100% local
> keyword filter runs first; only mails that pass it ever reach an LLM. Verified by
> [`tests/test_pipeline_privacy.py`](tests/test_pipeline_privacy.py).

## Features (V1)

- IMAP fetcher (`.env` driven) + Thunderbird MBOX reader
- Local rule-based filter (FR + EN keywords + your stack: Java/GeoServer/OpenLayers/K8s/PostGIS/Spring/Docker…)
- Pluggable extractor: `mock` (default, offline), `claude`, `ollama`, `openai` (stub)
- SQLite storage (single file, no server)
- HTML dashboard (FastAPI + Jinja2) — list, filter by techno/score/status, mark new/interesting/ignored/replied
- CLI: `jobmail fetch | serve | seed | classify`

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

LLM_PROVIDER=mock                     # mock | ollama | claude | openai
ANTHROPIC_API_KEY=sk-ant-...          # if LLM_PROVIDER=claude
ANTHROPIC_MODEL=claude-sonnet-4-6
OLLAMA_MODEL=llama3.1                 # if LLM_PROVIDER=ollama
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

# Re-classify cached emails after editing rules.py (no LLM call)
python -m jobmail classify
```

## Thunderbird

Thunderbird stores INBOX as an MBOX file at:
`%APPDATA%\Thunderbird\Profiles\<id>\ImapMail\<server>\INBOX`

To plug it, edit `jobmail/mail/thunderbird.py` and feed `read_mbox(Path(...))` into
`pipeline.run(source=...)`. Wire it as a CLI flag when ready (1-line addition).

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
├── extraction/      # base + mock + claude + ollama + openai (stub)
├── web/             # FastAPI + Jinja2 dashboard
└── cli.py           # entry-point
```

## Roadmap

- [ ] Thunderbird CLI flag (`jobmail fetch --mbox path`)
- [ ] OpenAI provider (structured outputs)
- [ ] Per-email "why was this kept?" inline matched-keyword viewer
- [ ] CSV / JSON export of offers
- [ ] Notifications Windows (toast) on new high-score offer
- [ ] Crontab via Windows Task Scheduler hint in README

## License

MIT.

---

*Built collaboratively with Claude (Opus 4.7).*
