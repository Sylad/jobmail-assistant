from __future__ import annotations

import sqlite3
import csv
import io
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..cleaner import (
    CleanerError,
    CleanerReport,
    delete_old_cleaner_backups,
    list_orphan_cleaner_temp_files,
    list_cleaner_backups,
    move_parsed_jobs_to_trash,
    move_orphan_cleaner_temp_files,
    move_scanned_regex_uids_to_trash,
    move_thunderbird_duplicates_to_trash,
    move_thunderbird_to_trash,
    move_to_delete,
    scan_parsed_job_mails,
    scan_old_promotions,
    scan_thunderbird_duplicates,
    scan_thunderbird_regex,
    scan_thunderbird_promotions,
)
from ..config import get_settings
from ..db import (
    all_known_technos,
    all_sender_domains,
    connect,
    get_offer,
    init_db,
    list_offers,
    update_status,
    upsert_offer,
)
from ..extraction import get_extractor
from ..extraction.base import PrivacyError
from ..mail.sources import build_mbox_source, resolve_mbox_paths
from ..models import OfferStatus
from ..models import RawEmail
from ..pipeline import run as run_pipeline
from .links import build_preferred_offer_terms, extract_offer_links


def _pipeline_process_active() -> tuple[bool, int | None]:
    """Look up /proc to see if any `jobmail fetch` / `jobmail dry-run` process
    is currently alive. More reliable than the DB-insert heuristic, which
    misses the long MBOX-parsing prelude where no commit happens."""
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return False, None
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except (OSError, PermissionError):
            continue
        if "jobmail" in cmdline and any(
            cmd in cmdline for cmd in (" fetch", " dry-run", " extract", " watch")
        ):
            return True, int(entry.name)
    return False, None


def _process_uptime(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
        # field 22 = start time (clock ticks since boot)
        start_ticks = int(fields[21])
        clk_tck = 100  # SC_CLK_TCK on Linux typical
        with open("/proc/uptime") as f:
            sys_uptime = float(f.read().split()[0])
        proc_uptime = sys_uptime - (start_ticks / clk_tck)
        m, s = divmod(int(proc_uptime), 60)
        return f"{m}m{s:02d}s"
    except (FileNotFoundError, IndexError, ValueError):
        return None


def _extract_email(s: str) -> str:
    """Return the first email address found in `s`. Handles 'Name <addr>',
    'addr', and 'Name addr@host' forms."""
    import re
    if not s:
        return ""
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", s)
    return m.group(0) if m else ""


def _compute_stats(conn: sqlite3.Connection) -> dict:
    n_emails = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
    n_jobs = conn.execute("SELECT COUNT(*) FROM emails WHERE job_related=1").fetchone()[0]
    n_offers = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    last = conn.execute("SELECT MAX(created_at) FROM emails").fetchone()[0]
    last_extract = conn.execute("SELECT MAX(extracted_at) FROM offers").fetchone()[0]

    is_running, pid = _pipeline_process_active()
    uptime = _process_uptime(pid) if pid else None

    # Phase heuristic + progress when running.
    phase = None
    progress = None  # 0..100 or None
    if is_running:
        if n_emails == 0:
            phase = "Parsing MBOX (lecture initiale du fichier)"
        elif n_offers == 0:
            phase = "Classification locale en cours"
            if n_emails:
                progress = min(100, n_jobs * 100 // max(n_emails, 1))
        else:
            phase = "Extraction LLM en cours"
            if n_jobs:
                progress = min(100, n_offers * 100 // n_jobs)

    return {
        "emails": n_emails,
        "jobs": n_jobs,
        "offers": n_offers,
        "is_running": is_running,
        "pid": pid,
        "uptime": uptime,
        "phase": phase,
        "progress": progress,
        "last_activity": last_extract or last,
    }

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["static_version"] = str(
    int(
        max(
            (BASE_DIR / "static" / "style.css").stat().st_mtime,
            (BASE_DIR / "static" / "assets" / "cleaner.css").stat().st_mtime,
            (BASE_DIR / "static" / "assets" / "cleaner.js").stat().st_mtime,
        )
    )
)


@dataclass
class CleanerScanJob:
    id: str
    status: str = "running"
    source: str = "regex"
    scanned_count: int = 0
    candidate_count: int = 0
    skipped_too_recent: int = 0
    skipped_safety: int = 0
    skipped_no_match: int = 0
    current_mailbox: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str = ""
    report: CleanerReport | None = None
    min_age_days: int = 7
    max_mails: int = 0
    scan_offset: int = 0
    regex_rules: list[tuple[str, str]] = field(default_factory=list)
    cancel_requested: bool = False


@dataclass
class CleanerMoveJob:
    id: str
    status: str = "running"
    source: str = "regex"
    moved_count: int = 0
    total_count: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str = ""
    report: CleanerReport | None = None
    min_age_days: int = 7
    max_mails: int = 0
    regex_rules: list[tuple[str, str]] = field(default_factory=list)
    cancel_requested: bool = False


@dataclass
class ReanalysisJob:
    id: str
    status: str = "running"
    total_count: int = 0
    processed_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    current_subject: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str = ""
    cancel_requested: bool = False


@dataclass
class RefreshJob:
    id: str
    status: str = "running"
    fetched_count: int = 0
    new_count: int = 0
    job_related_count: int = 0
    extracted_count: int = 0
    sent_to_llm_count: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str = ""


_cleaner_jobs: dict[str, CleanerScanJob] = {}
_cleaner_jobs_lock = threading.Lock()
_cleaner_move_jobs: dict[str, CleanerMoveJob] = {}
_cleaner_move_jobs_lock = threading.Lock()
_reanalysis_job: ReanalysisJob | None = None
_reanalysis_lock = threading.Lock()
_refresh_job: RefreshJob | None = None
_refresh_lock = threading.Lock()


def _refresh_payload(job: RefreshJob | None) -> dict:
    if job is None:
        return {
            "id": "",
            "status": "idle",
            "fetched_count": 0,
            "new_count": 0,
            "job_related_count": 0,
            "extracted_count": 0,
            "sent_to_llm_count": 0,
            "extraction_failed_count": 0,
            "elapsed_seconds": 0,
            "error": "",
        }
    elapsed = int((job.finished_at or time.time()) - job.started_at)
    return {
        "id": job.id,
        "status": job.status,
        "fetched_count": job.fetched_count,
        "new_count": job.new_count,
        "job_related_count": job.job_related_count,
        "extracted_count": job.extracted_count,
        "sent_to_llm_count": job.sent_to_llm_count,
        "extraction_failed_count": max(0, job.sent_to_llm_count - job.extracted_count),
        "elapsed_seconds": elapsed,
        "error": job.error,
    }


def _run_refresh_job(settings, job: RefreshJob) -> None:
    try:
        mbox_paths = resolve_mbox_paths(settings.cleaner_mbox_patterns)
        source = build_mbox_source(mbox_paths, settings=settings) if mbox_paths else None
        stats = run_pipeline(source=source, settings=settings)
        job.fetched_count = stats.fetched
        job.new_count = stats.new
        job.job_related_count = stats.job_related
        job.extracted_count = stats.extracted
        job.sent_to_llm_count = stats.sent_to_llm
        pending_attempted, pending_extracted = _extract_pending_job_offers(settings, limit=25)
        job.sent_to_llm_count += pending_attempted
        job.extracted_count += pending_extracted
        job.status = "done"
    except Exception as e:
        job.status = "error"
        job.error = str(e)
    finally:
        job.finished_at = time.time()


def _start_refresh_job(settings) -> RefreshJob:
    global _refresh_job
    with _refresh_lock:
        if _refresh_job is not None and _refresh_job.status == "running":
            return _refresh_job
        _refresh_job = RefreshJob(id=uuid.uuid4().hex)
        job = _refresh_job
    thread = threading.Thread(target=_run_refresh_job, args=(settings, job), daemon=True)
    thread.start()
    return job


def _extract_pending_job_offers(settings, *, limit: int) -> tuple[int, int]:
    """Retry recent job-related emails that were ingested while extraction failed."""
    if limit <= 0 or not _llm_provider_available(settings):
        return 0, 0

    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT e.uid, e.message_id, e.subject, e.sender, e.received_at, e.body_text, e.body_html
            FROM emails e
            LEFT JOIN offers o ON o.email_uid = e.uid
            WHERE e.job_related = 1
              AND o.id IS NULL
              AND e.subject != ''
              AND e.sender != ''
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        return 0, 0

    extractor = get_extractor(settings)
    attempted = 0
    extracted = 0
    for row in rows:
        attempted += 1
        email = RawEmail(
            uid=row["uid"],
            message_id=row["message_id"],
            subject=row["subject"],
            sender=row["sender"],
            received_at=datetime.fromisoformat(row["received_at"]),
            body_text=row["body_text"],
            body_html=row["body_html"] or "",
        )
        try:
            extraction = extractor.extract(email, settings.target_profile)
        except PrivacyError:
            continue
        except Exception:
            continue
        if _empty_extraction(extraction):
            continue
        with connect(settings.db_path) as conn:
            upsert_offer(conn, email.uid, extraction)
        extracted += 1
    return attempted, extracted


def _reanalysis_payload(job: ReanalysisJob | None) -> dict:
    if job is None:
        return {
            "id": "",
            "status": "idle",
            "total_count": 0,
            "processed_count": 0,
            "updated_count": 0,
            "failed_count": 0,
            "current_subject": "",
            "elapsed_seconds": 0,
            "progress": None,
            "error": "",
        }
    elapsed = int((job.finished_at or time.time()) - job.started_at)
    progress = round(job.processed_count / job.total_count * 100) if job.total_count else None
    return {
        "id": job.id,
        "status": job.status,
        "total_count": job.total_count,
        "processed_count": job.processed_count,
        "updated_count": job.updated_count,
        "failed_count": job.failed_count,
        "current_subject": job.current_subject,
        "elapsed_seconds": elapsed,
        "progress": progress,
        "error": job.error,
    }


def _llm_provider_available(settings) -> bool:
    if settings.llm_provider != "ollama":
        return True
    import httpx

    try:
        resp = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=2)
        resp.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def _empty_extraction(extraction) -> bool:
    return (
        not extraction.title
        and not extraction.company
        and not extraction.recruiter
        and not extraction.location
        and not extraction.technos
        and not extraction.summary
        and not extraction.offer_url
        and extraction.relevance_score == 0
    )


def _run_reanalysis_job(settings, job: ReanalysisJob) -> None:
    from datetime import datetime

    try:
        extractor = get_extractor(settings)
        with connect(settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT e.uid, e.message_id, e.subject, e.sender, e.received_at, e.body_text, e.body_html
                FROM emails e
                WHERE e.job_related = 1
                ORDER BY e.received_at DESC
                """
            ).fetchall()
        job.total_count = len(rows)
        for row in rows:
            if job.cancel_requested:
                job.status = "cancelled"
                return
            job.current_subject = row["subject"] or ""
            email = RawEmail(
                uid=row["uid"],
                message_id=row["message_id"],
                subject=row["subject"],
                sender=row["sender"],
                received_at=datetime.fromisoformat(row["received_at"]),
                body_text=row["body_text"],
                body_html=row["body_html"] or "",
            )
            try:
                extraction = extractor.extract(email, settings.target_profile)
            except PrivacyError:
                job.failed_count += 1
            except Exception:
                job.failed_count += 1
            else:
                if _empty_extraction(extraction):
                    job.failed_count += 1
                else:
                    with connect(settings.db_path) as conn:
                        upsert_offer(conn, email.uid, extraction)
                    job.updated_count += 1
            finally:
                job.processed_count += 1
        job.status = "done"
    except Exception as e:
        job.status = "error"
        job.error = str(e)
    finally:
        job.finished_at = time.time()


def _load_saved_regex_rules(settings) -> list[tuple[str, str]]:
    path = settings.cleaner_regex_rules_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        return []
    rules = raw.get("rules", raw if isinstance(raw, list) else [])
    loaded: list[tuple[str, str]] = []
    if not isinstance(rules, list):
        return []
    for item in rules:
        if not isinstance(item, dict):
            continue
        sender = str(item.get("sender_regex", "")).strip()
        subject = str(item.get("subject_regex", "")).strip()
        if sender or subject:
            loaded.append((sender, subject))
    return loaded


def _save_regex_rules(settings, rules: list[tuple[str, str]]) -> None:
    clean_rules = [{"sender_regex": sender, "subject_regex": subject} for sender, subject in rules if sender or subject]
    path = settings.cleaner_regex_rules_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rules": clean_rules}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def _cleaner_context(
    *,
    request: Request,
    settings,
    report: CleanerReport | None = None,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    scan_offset: int = 0,
    source: str = "thunderbird",
    sender_regex: str = "",
    subject_regex: str = "",
    regex_rules: list[tuple[str, str]] | None = None,
    regex_job_id: str = "",
    error: str = "",
    moved_count: int = 0,
    moved_destination: str = "",
    backup_deleted_count: int = 0,
    backup_deleted_bytes: int = 0,
    backup_retention_days: int | None = None,
    temp_moved_count: int = 0,
    temp_moved_bytes: int = 0,
    temp_destination: str = "",
) -> dict:
    if regex_rules is None and not sender_regex and not subject_regex:
        regex_rules = _load_saved_regex_rules(settings)
    display_rules = _display_regex_rules(regex_rules, sender_regex, subject_regex)
    backup_summary = list_cleaner_backups(settings, retention_days=backup_retention_days)
    temp_summary = list_orphan_cleaner_temp_files(settings)
    return {
        "request": request,
        "report": report,
        "min_age_days": min_age_days or settings.cleaner_min_age_days,
        "max_mails": settings.cleaner_max_mails if max_mails is None else max_mails,
        "scan_offset": max(0, scan_offset),
        "source": source,
        "sender_regex": sender_regex,
        "subject_regex": subject_regex,
        "regex_rules": display_rules,
        "regex_job_id": regex_job_id,
        "delete_folder": settings.cleaner_delete_folder,
        "mbox_patterns": settings.cleaner_mbox_patterns,
        "error": error,
        "moved_count": moved_count,
        "moved_destination": moved_destination,
        "backup_summary": backup_summary,
        "backup_total_size": _format_bytes(backup_summary.total_bytes),
        "backup_eligible_size": _format_bytes(backup_summary.eligible_bytes),
        "backup_deleted_count": backup_deleted_count,
        "backup_deleted_size": _format_bytes(backup_deleted_bytes),
        "temp_summary": temp_summary,
        "temp_total_size": _format_bytes(temp_summary.total_bytes),
        "temp_moved_count": temp_moved_count,
        "temp_moved_size": _format_bytes(temp_moved_bytes),
        "temp_destination": temp_destination,
        "provider": settings.llm_provider,
        "imap_enabled": settings.imap_enabled,
    }


def _display_regex_rules(
    regex_rules: list[tuple[str, str]] | None,
    sender_regex: str = "",
    subject_regex: str = "",
) -> list[tuple[str, str]]:
    rules = regex_rules if regex_rules is not None else []
    if not rules and (sender_regex or subject_regex):
        rules = [(sender_regex, subject_regex)]
    visible = [(sender, subject) for sender, subject in rules if sender or subject]
    while len(visible) < 5:
        visible.append(("", ""))
    return visible


def _form_regex_rules(sender_values: list[str], subject_values: list[str], sender_regex: str, subject_regex: str) -> list[tuple[str, str]]:
    max_len = max(len(sender_values), len(subject_values))
    rules: list[tuple[str, str]] = []
    for index in range(max_len):
        sender = sender_values[index].strip() if index < len(sender_values) else ""
        subject = subject_values[index].strip() if index < len(subject_values) else ""
        if sender or subject:
            rules.append((sender, subject))
    if not rules and (sender_regex.strip() or subject_regex.strip()):
        rules.append((sender_regex.strip(), subject_regex.strip()))
    return rules


def _report_to_csv(report: CleanerReport) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["uid", "source", "mailbox", "date", "sender", "subject", "reason", "source_path"])
    for candidate in report.candidates:
        writer.writerow([
            candidate.uid,
            candidate.source,
            candidate.mailbox,
            candidate.received_at.isoformat(),
            candidate.sender,
            candidate.subject,
            candidate.reason,
            candidate.source_path,
        ])
    return out.getvalue()


def _candidate_payload(candidate) -> dict:
    return {
        "uid": candidate.uid,
        "received_at": candidate.received_at.isoformat(),
        "received_date": candidate.received_at.strftime("%Y-%m-%d"),
        "sender": candidate.sender,
        "subject": candidate.subject,
        "reason": candidate.reason,
        "source": candidate.source,
        "mailbox": candidate.mailbox,
        "source_path": candidate.source_path,
        "offer_id": candidate.offer_id,
        "status": candidate.status,
        "score": candidate.score,
        "company": candidate.company,
        "duplicate_of": candidate.duplicate_of,
        "can_move": candidate.can_move,
    }


def _report_payload(report: CleanerReport) -> dict:
    return {
        "scanned_count": report.scanned_count,
        "candidate_count": report.candidate_count,
        "skipped_too_recent": report.skipped_too_recent,
        "skipped_safety": report.skipped_safety,
        "skipped_no_match": report.skipped_no_match,
        "top_senders": [{"sender": sender, "count": count} for sender, count in report.top_senders],
        "candidates": [_candidate_payload(candidate) for candidate in report.candidates],
    }


def _cleaner_state_payload(settings, *, source: str = "thunderbird") -> dict:
    return {
        "source": source,
        "min_age_days": settings.cleaner_min_age_days,
        "max_mails": settings.cleaner_max_mails,
        "scan_offset": 0,
        "delete_folder": settings.cleaner_delete_folder,
        "mbox_patterns": settings.cleaner_mbox_patterns,
        "regex_rules": [
            {"sender_regex": sender, "subject_regex": subject}
            for sender, subject in _display_regex_rules(_load_saved_regex_rules(settings))
        ],
        "imap_enabled": settings.imap_enabled,
    }


def _job_payload(job: CleanerScanJob) -> dict:
    elapsed = int((job.finished_at or time.time()) - job.started_at)
    return {
        "id": job.id,
        "status": job.status,
        "scanned_count": job.scanned_count,
        "candidate_count": job.candidate_count,
        "skipped_too_recent": job.skipped_too_recent,
        "skipped_safety": job.skipped_safety,
        "skipped_no_match": job.skipped_no_match,
        "current_mailbox": job.current_mailbox,
        "elapsed_seconds": elapsed,
        "error": job.error,
        "result_url": f"/cleaner/scan/result/{job.id}" if job.status == "done" else "",
        "result_json_url": f"/cleaner/scan/result-json/{job.id}" if job.status == "done" else "",
        "cancel_url": f"/cleaner/scan/cancel/{job.id}" if job.status == "running" else "",
    }


def _move_job_payload(job: CleanerMoveJob) -> dict:
    elapsed = int((job.finished_at or time.time()) - job.started_at)
    return {
        "id": job.id,
        "status": job.status,
        "moved_count": job.moved_count,
        "total_count": job.total_count,
        "elapsed_seconds": elapsed,
        "error": job.error,
        "result_url": f"/cleaner/move/status/{job.id}/result" if job.status == "done" else "",
        "result_json_url": f"/cleaner/move/status/{job.id}/result-json" if job.status == "done" else "",
        "cancel_url": f"/cleaner/move/cancel/{job.id}" if job.status == "running" else "",
    }


def _regex_job_move_context(job_id: str) -> tuple[list[str], CleanerReport, list[tuple[str, str]], int, int] | None:
    with _cleaner_jobs_lock:
        job = _cleaner_jobs.get(job_id)
        if job is None or job.status != "done" or job.report is None:
            return None
        report = job.report
        uids = [candidate.uid for candidate in report.candidates]
        return uids, report, list(job.regex_rules), job.min_age_days, job.max_mails


def create_app() -> FastAPI:
    settings = get_settings()
    init_db(settings.db_path)

    app = FastAPI(title="JobMail Assistant", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        status: str | None = Query(None),
        techno: str | None = Query(None),
        sender: str | None = Query(None),
        since_days: int | None = Query(None, ge=0, le=365),
        min_score: int = Query(0, ge=0, le=10),
        esn: str = Query("all", pattern="^(all|hide|only)$"),
    ):
        with connect(settings.db_path) as conn:
            status_filter = OfferStatus(status) if status else None
            offers = list_offers(
                conn,
                status=status_filter,
                techno=techno,
                min_score=min_score,
                sender_contains=sender,
                since_days=since_days,
                esn_mode=esn,
            )
            technos = all_known_technos(conn)
            senders = all_sender_domains(conn)
            stats = _compute_stats(conn)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "offers": offers,
                "technos": technos,
                "senders": senders,
                "all_statuses": [s.value for s in OfferStatus],
                "current_status": status or "",
                "current_techno": techno or "",
                "current_sender": sender or "",
                "current_since_days": since_days or 0,
                "current_min_score": min_score,
                "current_esn": esn,
                "provider": settings.llm_provider,
                "imap_enabled": settings.imap_enabled,
                "stats": stats,
                "reanalysis_job": _reanalysis_payload(_reanalysis_job),
            },
        )

    @app.get("/api/status")
    def api_status():
        with connect(settings.db_path) as conn:
            return _compute_stats(conn)

    @app.post("/offers/reanalyze/start")
    def start_offer_reanalysis():
        global _reanalysis_job
        with _reanalysis_lock:
            if _reanalysis_job is not None and _reanalysis_job.status == "running":
                return _reanalysis_payload(_reanalysis_job)
            if not _llm_provider_available(settings):
                raise HTTPException(status_code=503, detail=f"Provider {settings.llm_provider!r} indisponible.")
            _reanalysis_job = ReanalysisJob(id=uuid.uuid4().hex)
            thread = threading.Thread(
                target=_run_reanalysis_job,
                args=(settings, _reanalysis_job),
                daemon=True,
            )
            thread.start()
            return _reanalysis_payload(_reanalysis_job)

    @app.get("/offers/reanalyze/status")
    def offer_reanalysis_status():
        return _reanalysis_payload(_reanalysis_job)

    @app.post("/offers/reanalyze/cancel")
    def cancel_offer_reanalysis():
        with _reanalysis_lock:
            if _reanalysis_job is not None and _reanalysis_job.status == "running":
                _reanalysis_job.cancel_requested = True
                return _reanalysis_payload(_reanalysis_job)
            return _reanalysis_payload(_reanalysis_job)

    @app.get("/cleaner", response_class=HTMLResponse)
    def cleaner(request: Request):
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(request=request, settings=settings)
            | {"cleaner_initial_state": _cleaner_state_payload(settings)},
        )

    @app.get("/cleaner/state")
    def cleaner_state(source: str = Query("thunderbird")):
        if source not in {"thunderbird", "regex", "parsed_jobs", "duplicates", "imap"}:
            raise HTTPException(status_code=400, detail="Source de cleaner inconnue.")
        return _cleaner_state_payload(settings, source=source)

    @app.post("/cleaner/regex-rules")
    def cleaner_save_regex_rules(payload: dict):
        raw_rules = payload.get("rules", [])
        if not isinstance(raw_rules, list):
            raise HTTPException(status_code=400, detail="Format de regles invalide.")
        sender_values: list[str] = []
        subject_values: list[str] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            sender_values.append(str(item.get("sender_regex", "")))
            subject_values.append(str(item.get("subject_regex", "")))
        regex_rules = _form_regex_rules(sender_values, subject_values, "", "")
        _save_regex_rules(settings, regex_rules)
        return {
            "saved": True,
            "regex_rules": [
                {"sender_regex": sender, "subject_regex": subject}
                for sender, subject in _display_regex_rules(regex_rules)
            ],
        }

    @app.post("/cleaner/backups/cleanup", response_class=HTMLResponse)
    def cleaner_backup_cleanup(
        request: Request,
        retention_days: int = Form(settings.cleaner_backup_retention_days),
        confirm_cleanup: str = Form(""),
    ):
        if confirm_cleanup != "yes":
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                settings=settings,
                backup_retention_days=retention_days,
                error="Confirmation obligatoire avant de nettoyer les backups.",
                ),
                status_code=400,
            )
        cleanup = delete_old_cleaner_backups(settings, retention_days=retention_days)
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                backup_deleted_count=cleanup.deleted_count,
                backup_deleted_bytes=cleanup.deleted_bytes,
                backup_retention_days=retention_days,
            ),
        )

    @app.post("/cleaner/temp/cleanup", response_class=HTMLResponse)
    def cleaner_temp_cleanup(
        request: Request,
        confirm_temp_cleanup: str = Form(""),
    ):
        if confirm_temp_cleanup != "yes":
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                    settings=settings,
                    error="Confirmation obligatoire avant de deplacer les temporaires orphelins.",
                ),
                status_code=400,
            )
        destination = Path("/mnt/c/Users/Sylvain Ladoire/Documents/JobMail-Thunderbird-Backups")
        try:
            cleanup = move_orphan_cleaner_temp_files(settings, destination_root=destination)
        except CleanerError as e:
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(request=request, settings=settings, error=str(e)),
                status_code=400,
            )
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                temp_moved_count=cleanup.moved_count,
                temp_moved_bytes=cleanup.moved_bytes,
                temp_destination=str(cleanup.destination),
            ),
        )

    @app.get("/cleaner/jobs", response_class=HTMLResponse)
    def cleaner_jobs(request: Request):
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(request=request, settings=settings, source="parsed_jobs")
            | {"cleaner_initial_state": _cleaner_state_payload(settings, source="parsed_jobs")},
        )

    @app.get("/cleaner/duplicates", response_class=HTMLResponse)
    def cleaner_duplicates(request: Request):
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(request=request, settings=settings, source="duplicates")
            | {"cleaner_initial_state": _cleaner_state_payload(settings, source="duplicates")},
        )

    @app.post("/cleaner/scan", response_class=HTMLResponse)
    def cleaner_scan(
        request: Request,
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
        scan_offset: int = Form(0),
        source: str = Form("thunderbird"),
        sender_regex: str = Form(""),
        subject_regex: str = Form(""),
        sender_regex_rule: list[str] = Form(default=[]),
        subject_regex_rule: list[str] = Form(default=[]),
        export_csv: str = Form(""),
    ):
        regex_rules = _form_regex_rules(sender_regex_rule, subject_regex_rule, sender_regex, subject_regex)
        try:
            if source == "imap":
                report = scan_old_promotions(
                    settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                )
            elif source == "parsed_jobs":
                report = scan_parsed_job_mails(
                    settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                )
            elif source == "duplicates":
                report = scan_thunderbird_duplicates(
                    settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                )
            elif source == "regex":
                _save_regex_rules(settings, regex_rules)
                report = scan_thunderbird_regex(
                    settings,
                    sender_regex=sender_regex,
                    subject_regex=subject_regex,
                    regex_rules=regex_rules,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                )
            else:
                source = "thunderbird"
                report = scan_thunderbird_promotions(
                    settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                    skip_mails=max(0, scan_offset),
                )
        except CleanerError as e:
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                    settings=settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                    scan_offset=scan_offset,
                    source=source,
                    sender_regex=sender_regex,
                    subject_regex=subject_regex,
                    regex_rules=regex_rules,
                    error=str(e),
                ),
                status_code=400,
            )

        if export_csv:
            return Response(
                content=_report_to_csv(report),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=jobmail-cleaner-report.csv"},
            )

        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                report=report,
                min_age_days=min_age_days,
                max_mails=max_mails,
                scan_offset=scan_offset,
                source=source,
                sender_regex=sender_regex,
                subject_regex=subject_regex,
                regex_rules=regex_rules,
            ),
        )

    @app.post("/cleaner/scan/start")
    def cleaner_scan_start(
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
        scan_offset: int = Form(0),
        source: str = Form("regex"),
        sender_regex: str = Form(""),
        subject_regex: str = Form(""),
        sender_regex_rule: list[str] = Form(default=[]),
        subject_regex_rule: list[str] = Form(default=[]),
    ):
        if source not in {"thunderbird", "regex", "parsed_jobs", "duplicates", "imap"}:
            raise HTTPException(status_code=400, detail="Source de scan inconnue.")

        regex_rules = _form_regex_rules(sender_regex_rule, subject_regex_rule, sender_regex, subject_regex)
        if source == "regex":
            _save_regex_rules(settings, regex_rules)
        job = CleanerScanJob(
            id=uuid.uuid4().hex,
            source=source,
            min_age_days=min_age_days,
            max_mails=max_mails,
            scan_offset=max(0, scan_offset),
            regex_rules=regex_rules,
        )
        with _cleaner_jobs_lock:
            _cleaner_jobs[job.id] = job

        def run_job() -> None:
            def progress(report: CleanerReport, mailbox: str) -> None:
                with _cleaner_jobs_lock:
                    job.scanned_count = report.scanned_count
                    job.candidate_count = report.candidate_count
                    job.skipped_too_recent = report.skipped_too_recent
                    job.skipped_safety = report.skipped_safety
                    job.skipped_no_match = report.skipped_no_match
                    job.current_mailbox = mailbox

            def should_cancel() -> bool:
                with _cleaner_jobs_lock:
                    return job.cancel_requested

            try:
                if source == "imap":
                    report = scan_old_promotions(
                        settings,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        progress_callback=progress,
                        should_cancel=should_cancel,
                    )
                elif source == "parsed_jobs":
                    report = scan_parsed_job_mails(
                        settings,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        progress_callback=progress,
                        should_cancel=should_cancel,
                    )
                elif source == "duplicates":
                    report = scan_thunderbird_duplicates(
                        settings,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        progress_callback=progress,
                        should_cancel=should_cancel,
                    )
                elif source == "regex":
                    report = scan_thunderbird_regex(
                        settings,
                        sender_regex=sender_regex,
                        subject_regex=subject_regex,
                        regex_rules=regex_rules,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        progress_callback=progress,
                        should_cancel=should_cancel,
                    )
                else:
                    report = scan_thunderbird_promotions(
                        settings,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        skip_mails=max(0, scan_offset),
                        progress_callback=progress,
                        should_cancel=should_cancel,
                    )
            except CleanerError as e:
                with _cleaner_jobs_lock:
                    job.status = "error"
                    job.error = str(e)
                    job.finished_at = time.time()
                return
            except Exception as e:
                with _cleaner_jobs_lock:
                    job.status = "error"
                    job.error = f"Erreur inattendue pendant le scan: {e}"
                    job.finished_at = time.time()
                return
            with _cleaner_jobs_lock:
                job.report = report
                job.scanned_count = report.scanned_count
                job.candidate_count = report.candidate_count
                job.skipped_too_recent = report.skipped_too_recent
                job.skipped_safety = report.skipped_safety
                job.skipped_no_match = report.skipped_no_match
                job.current_mailbox = ""
                job.status = "cancelled" if job.cancel_requested else "done"
                job.finished_at = time.time()

        threading.Thread(target=run_job, daemon=True).start()
        return _job_payload(job)

    @app.get("/cleaner/scan/status/{job_id}")
    def cleaner_scan_status(job_id: str):
        with _cleaner_jobs_lock:
            job = _cleaner_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Scan introuvable.")
            return _job_payload(job)

    @app.post("/cleaner/scan/cancel/{job_id}")
    def cleaner_scan_cancel(job_id: str):
        with _cleaner_jobs_lock:
            job = _cleaner_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Scan introuvable.")
            if job.status != "running":
                return _job_payload(job)
            job.cancel_requested = True
            return _job_payload(job)

    @app.get("/cleaner/scan/result/{job_id}", response_class=HTMLResponse)
    def cleaner_scan_result(request: Request, job_id: str):
        with _cleaner_jobs_lock:
            job = _cleaner_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Scan introuvable.")
            if job.status == "error":
                return templates.TemplateResponse(
                    request,
                    "cleaner.html",
                    _cleaner_context(
                        request=request,
                        settings=settings,
                        min_age_days=job.min_age_days,
                        max_mails=job.max_mails,
                        scan_offset=job.scan_offset,
                        source=job.source,
                        regex_rules=job.regex_rules,
                        error=job.error,
                    ),
                    status_code=400,
                )
            if job.status == "cancelled":
                return templates.TemplateResponse(
                    request,
                    "cleaner.html",
                    _cleaner_context(
                        request=request,
                        settings=settings,
                        min_age_days=job.min_age_days,
                        max_mails=job.max_mails,
                        scan_offset=job.scan_offset,
                        source=job.source,
                        regex_rules=job.regex_rules,
                        error="Scan annule. Aucun deplacement n'a ete lance.",
                    ),
                    status_code=400,
                )
            if job.status != "done" or job.report is None:
                raise HTTPException(status_code=409, detail="Scan encore en cours.")
            report = job.report
            regex_rules = list(job.regex_rules)

        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                report=report,
                min_age_days=job.min_age_days,
                max_mails=job.max_mails,
                scan_offset=job.scan_offset,
                source=job.source,
                regex_rules=regex_rules,
                regex_job_id=job_id,
            ),
        )

    @app.get("/cleaner/scan/result-json/{job_id}")
    def cleaner_scan_result_json(job_id: str):
        with _cleaner_jobs_lock:
            job = _cleaner_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Scan introuvable.")
            if job.status == "error":
                raise HTTPException(status_code=400, detail=job.error)
            if job.status == "cancelled":
                raise HTTPException(status_code=400, detail="Scan annule. Aucun deplacement n'a ete lance.")
            if job.status != "done" or job.report is None:
                raise HTTPException(status_code=409, detail="Scan encore en cours.")
            return {
                "job_id": job.id,
                "source": job.source,
                "min_age_days": job.min_age_days,
                "max_mails": job.max_mails,
                "scan_offset": job.scan_offset,
                "regex_job_id": job.id if job.source == "regex" else "",
                "regex_rules": [
                    {"sender_regex": sender, "subject_regex": subject}
                    for sender, subject in _display_regex_rules(job.regex_rules)
                ],
                "delete_folder": settings.cleaner_delete_folder,
                "report": _report_payload(job.report),
            }

    @app.post("/cleaner/move-to-delete", response_class=HTMLResponse)
    def cleaner_move_to_delete(
        request: Request,
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
        selected_uid: list[str] = Form(default=[]),
        confirm_move: str = Form(""),
    ):
        if confirm_move != "yes":
            report = CleanerReport(
                scanned_count=len(selected_uid),
                candidates=[],
            )
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                    settings=settings,
                    report=report,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                    error="Confirmation obligatoire avant tout deplacement.",
                ),
                status_code=400,
            )
        try:
            moved_count, report = move_to_delete(
                settings,
                uids=selected_uid,
                min_age_days=min_age_days,
                max_mails=max_mails,
            )
        except CleanerError as e:
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                    settings=settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                    error=str(e),
                ),
                status_code=400,
            )

        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                report=report,
                min_age_days=min_age_days,
                max_mails=max_mails,
                moved_count=moved_count,
            ),
        )

    @app.get("/cleaner/move-to-delete")
    def cleaner_move_to_delete_get():
        return RedirectResponse(url="/cleaner", status_code=303)

    @app.get("/cleaner/move-thunderbird-to-trash")
    def cleaner_move_thunderbird_to_trash_get():
        return RedirectResponse(url="/cleaner", status_code=303)

    @app.post("/cleaner/move-thunderbird-to-trash/start")
    def cleaner_move_thunderbird_to_trash_start(
        confirm_move: str = Form(""),
        confirm_thunderbird_closed: str = Form(""),
        source: str = Form("thunderbird"),
        regex_job_id: str = Form(""),
        selected_uid: list[str] = Form(default=[]),
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
    ):
        if confirm_move != "yes" or confirm_thunderbird_closed != "yes":
            raise HTTPException(status_code=400, detail="Confirmation obligatoire et Thunderbird doit etre ferme avant l'action.")

        selected_uids = list(selected_uid)
        scan_report: CleanerReport | None = None
        regex_rules: list[tuple[str, str]] = []
        if source == "regex":
            requested_uids = set(selected_uids)
            job_context = _regex_job_move_context(regex_job_id) if regex_job_id else None
            if job_context is None:
                raise HTTPException(
                    status_code=400,
                    detail="Le resultat du scan n'est plus disponible. Relance un scan regex avant de deplacer.",
                )
            scanned_uids, scan_report, regex_rules, min_age_days, max_mails = job_context
            selected_uids = [uid for uid in scanned_uids if not requested_uids or uid in requested_uids]
        elif source not in {"thunderbird", "parsed_jobs", "duplicates"}:
            raise HTTPException(status_code=400, detail="Source Thunderbird inconnue.")
        if not selected_uids:
            raise HTTPException(status_code=400, detail="Aucun mail selectionne.")

        move_job = CleanerMoveJob(
            id=uuid.uuid4().hex,
            source=source,
            total_count=len(selected_uids),
            min_age_days=min_age_days,
            max_mails=max_mails,
            regex_rules=regex_rules,
        )
        with _cleaner_move_jobs_lock:
            _cleaner_move_jobs[move_job.id] = move_job

        def run_move() -> None:
            def progress(moved: int) -> None:
                with _cleaner_move_jobs_lock:
                    move_job.moved_count = moved

            try:
                with _cleaner_move_jobs_lock:
                    cancelled = move_job.cancel_requested
                if cancelled:
                    with _cleaner_move_jobs_lock:
                        move_job.status = "cancelled"
                        move_job.finished_at = time.time()
                    return
                if source == "regex":
                    moved_count, report = move_scanned_regex_uids_to_trash(
                        settings,
                        uids=selected_uids,
                        min_age_days=min_age_days,
                        progress_callback=progress,
                    )
                    if scan_report is not None:
                        report.scanned_count = scan_report.scanned_count
                elif source == "parsed_jobs":
                    moved_count, report = move_parsed_jobs_to_trash(
                        settings,
                        uids=selected_uids,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        progress_callback=progress,
                    )
                elif source == "duplicates":
                    moved_count, report = move_thunderbird_duplicates_to_trash(
                        settings,
                        uids=selected_uids,
                        min_age_days=min_age_days,
                        progress_callback=progress,
                    )
                else:
                    moved_count, report = move_thunderbird_to_trash(
                        settings,
                        uids=selected_uids,
                        min_age_days=min_age_days,
                        max_mails=max_mails,
                        progress_callback=progress,
                    )
            except CleanerError as e:
                with _cleaner_move_jobs_lock:
                    move_job.status = "error"
                    move_job.error = str(e)
                    move_job.finished_at = time.time()
                return
            except Exception as e:
                with _cleaner_move_jobs_lock:
                    move_job.status = "error"
                    move_job.error = f"Erreur inattendue pendant le deplacement: {e}"
                    move_job.finished_at = time.time()
                return
            with _cleaner_move_jobs_lock:
                move_job.status = "done"
                move_job.moved_count = moved_count
                move_job.report = report
                move_job.finished_at = time.time()

        threading.Thread(target=run_move, daemon=True).start()
        return _move_job_payload(move_job)

    @app.get("/cleaner/move/status/{job_id}")
    def cleaner_move_status(job_id: str):
        with _cleaner_move_jobs_lock:
            job = _cleaner_move_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Deplacement introuvable.")
            return _move_job_payload(job)

    @app.post("/cleaner/move/cancel/{job_id}")
    def cleaner_move_cancel(job_id: str):
        with _cleaner_move_jobs_lock:
            job = _cleaner_move_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Deplacement introuvable.")
            if job.status != "running":
                return _move_job_payload(job)
            job.cancel_requested = True
            return _move_job_payload(job)

    @app.get("/cleaner/move/status/{job_id}/result", response_class=HTMLResponse)
    def cleaner_move_result(request: Request, job_id: str):
        with _cleaner_move_jobs_lock:
            job = _cleaner_move_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Deplacement introuvable.")
            if job.status == "error":
                return templates.TemplateResponse(
                    request,
                    "cleaner.html",
                    _cleaner_context(
                        request=request,
                        settings=settings,
                        min_age_days=job.min_age_days,
                        max_mails=job.max_mails,
                        source=job.source,
                        regex_rules=job.regex_rules,
                        error=job.error,
                    ),
                    status_code=400,
                )
            if job.status == "cancelled":
                return templates.TemplateResponse(
                    request,
                    "cleaner.html",
                    _cleaner_context(
                        request=request,
                        settings=settings,
                        min_age_days=job.min_age_days,
                        max_mails=job.max_mails,
                        source=job.source,
                        regex_rules=job.regex_rules,
                        error="Deplacement annule avant modification Thunderbird.",
                    ),
                    status_code=400,
                )
            if job.status != "done" or job.report is None:
                raise HTTPException(status_code=409, detail="Deplacement encore en cours.")
            report = job.report
            regex_rules = list(job.regex_rules)

        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                report=report,
                min_age_days=job.min_age_days,
                max_mails=job.max_mails,
                source=job.source,
                regex_rules=regex_rules,
                moved_count=job.moved_count,
                moved_destination="corbeille Thunderbird",
            ),
        )

    @app.get("/cleaner/move/status/{job_id}/result-json")
    def cleaner_move_result_json(job_id: str):
        with _cleaner_move_jobs_lock:
            job = _cleaner_move_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Deplacement introuvable.")
            if job.status == "error":
                raise HTTPException(status_code=400, detail=job.error)
            if job.status == "cancelled":
                raise HTTPException(status_code=400, detail="Deplacement annule avant modification Thunderbird.")
            if job.status != "done" or job.report is None:
                raise HTTPException(status_code=409, detail="Deplacement encore en cours.")
            return {
                "moved_count": job.moved_count,
                "moved_destination": "corbeille Thunderbird",
                "source": job.source,
                "min_age_days": job.min_age_days,
                "max_mails": job.max_mails,
                "regex_rules": [
                    {"sender_regex": sender, "subject_regex": subject}
                    for sender, subject in _display_regex_rules(job.regex_rules)
                ],
                "report": _report_payload(job.report),
            }

    @app.post("/cleaner/move-thunderbird-to-trash", response_class=HTMLResponse)
    def cleaner_move_thunderbird_to_trash(
        request: Request,
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
        selected_uid: list[str] = Form(default=[]),
        confirm_move: str = Form(""),
        confirm_thunderbird_closed: str = Form(""),
        source: str = Form("thunderbird"),
        sender_regex: str = Form(""),
        subject_regex: str = Form(""),
        sender_regex_rule: list[str] = Form(default=[]),
        subject_regex_rule: list[str] = Form(default=[]),
        regex_job_id: str = Form(""),
    ):
        regex_rules = _form_regex_rules(sender_regex_rule, subject_regex_rule, sender_regex, subject_regex)
        if confirm_move != "yes" or confirm_thunderbird_closed != "yes":
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                    settings=settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                    source=source,
                    sender_regex=sender_regex,
                    subject_regex=subject_regex,
                    regex_rules=regex_rules,
                    error="Confirmation obligatoire et Thunderbird doit etre ferme avant l'action.",
                ),
                status_code=400,
            )
        try:
            if source == "parsed_jobs":
                moved_count, report = move_parsed_jobs_to_trash(
                    settings,
                    uids=selected_uid,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                )
            elif source == "duplicates":
                moved_count, report = move_thunderbird_duplicates_to_trash(
                    settings,
                    uids=selected_uid,
                    min_age_days=min_age_days,
                )
            elif source == "regex":
                _save_regex_rules(settings, regex_rules)
                job_context = _regex_job_move_context(regex_job_id) if regex_job_id else None
                if job_context is None:
                    raise CleanerError(
                        "Le resultat du scan n'est plus disponible. Relance un scan regex avant de deplacer."
                    )
                safe_uids, scan_report, regex_rules, min_age_days, max_mails = job_context
                if not safe_uids:
                    raise CleanerError("Le scan termine ne contient aucun candidat a deplacer.")
                moved_count, report = move_scanned_regex_uids_to_trash(
                    settings,
                    uids=safe_uids,
                    min_age_days=min_age_days,
                )
                report.scanned_count = scan_report.scanned_count
            else:
                moved_count, report = move_thunderbird_to_trash(
                    settings,
                    uids=selected_uid,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                )
        except CleanerError as e:
            return templates.TemplateResponse(
                request,
                "cleaner.html",
                _cleaner_context(
                    request=request,
                    settings=settings,
                    min_age_days=min_age_days,
                    max_mails=max_mails,
                    source=source,
                    sender_regex=sender_regex,
                    subject_regex=subject_regex,
                    regex_rules=regex_rules,
                    regex_job_id=regex_job_id,
                    error=str(e),
                ),
                status_code=400,
            )

        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(
                request=request,
                settings=settings,
                report=report,
                min_age_days=min_age_days,
                max_mails=max_mails,
                source=source,
                sender_regex=sender_regex,
                subject_regex=subject_regex,
                regex_rules=regex_rules,
                regex_job_id=regex_job_id,
                moved_count=moved_count,
            ),
        )

    @app.get("/offers/{offer_id}", response_class=HTMLResponse)
    def offer_detail(request: Request, offer_id: int):
        with connect(settings.db_path) as conn:
            offer = get_offer(conn, offer_id, with_body=True)
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")
        return templates.TemplateResponse(
            request,
            "offer.html",
            {
                "offer": offer,
                "recruiter_email": _extract_email(offer.extraction.recruiter or offer.sender),
                "offer_links": extract_offer_links(
                    offer.body_text,
                    offer.body_html,
                    preferred_terms=build_preferred_offer_terms(
                        offer.extraction.title,
                        offer.extraction.company,
                        offer.subject,
                    ),
                    preferred_url=offer.extraction.offer_url,
                ),
                "all_statuses": [s.value for s in OfferStatus],
                "provider": settings.llm_provider,
                "imap_enabled": settings.imap_enabled,
            },
        )

    @app.post("/offers/{offer_id}/status")
    def set_status(
        offer_id: int,
        status: str = Form(...),
        return_to: str = Form(""),
    ):
        try:
            new_status = OfferStatus(status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        with connect(settings.db_path) as conn:
            if get_offer(conn, offer_id) is None:
                raise HTTPException(status_code=404, detail="Offer not found")
            update_status(conn, offer_id, new_status)
        # If invoked from the dashboard inline buttons, preserve the active
        # filter set by sending the user back to the same URL.
        target = return_to if return_to.startswith("/") else f"/offers/{offer_id}"
        return RedirectResponse(url=target, status_code=303)

    @app.post("/refresh")
    def refresh():
        _start_refresh_job(settings)
        return RedirectResponse(url="/?refreshing=1", status_code=303)

    @app.post("/refresh/start")
    def refresh_start():
        job = _start_refresh_job(settings)
        return JSONResponse(_refresh_payload(job))

    @app.get("/refresh/status")
    def refresh_status():
        return JSONResponse(_refresh_payload(_refresh_job))

    return app


app = create_app()
