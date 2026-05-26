from __future__ import annotations

import sqlite3
import csv
import io
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
)
from ..models import OfferStatus
from ..pipeline import run as run_pipeline
from .links import extract_offer_links


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
    regex_rules: list[tuple[str, str]] = field(default_factory=list)
    cancel_requested: bool = False


@dataclass
class CleanerMoveJob:
    id: str
    status: str = "running"
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


_cleaner_jobs: dict[str, CleanerScanJob] = {}
_cleaner_jobs_lock = threading.Lock()
_cleaner_move_jobs: dict[str, CleanerMoveJob] = {}
_cleaner_move_jobs_lock = threading.Lock()


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
        "max_mails": max_mails or settings.cleaner_max_mails,
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
                "provider": settings.llm_provider,
                "imap_enabled": settings.imap_enabled,
                "stats": stats,
            },
        )

    @app.get("/api/status")
    def api_status():
        with connect(settings.db_path) as conn:
            return _compute_stats(conn)

    @app.get("/cleaner", response_class=HTMLResponse)
    def cleaner(request: Request):
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(request=request, settings=settings),
        )

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
            _cleaner_context(request=request, settings=settings, source="parsed_jobs"),
        )

    @app.get("/cleaner/duplicates", response_class=HTMLResponse)
    def cleaner_duplicates(request: Request):
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(request=request, settings=settings, source="duplicates"),
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
        source: str = Form("regex"),
        sender_regex: str = Form(""),
        subject_regex: str = Form(""),
        sender_regex_rule: list[str] = Form(default=[]),
        subject_regex_rule: list[str] = Form(default=[]),
    ):
        if source != "regex":
            raise HTTPException(status_code=400, detail="Le scan progressif est disponible pour les regex Thunderbird.")

        regex_rules = _form_regex_rules(sender_regex_rule, subject_regex_rule, sender_regex, subject_regex)
        _save_regex_rules(settings, regex_rules)
        job = CleanerScanJob(
            id=uuid.uuid4().hex,
            min_age_days=min_age_days,
            max_mails=max_mails,
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
                        source="regex",
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
                        source="regex",
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
                source="regex",
                regex_rules=regex_rules,
                regex_job_id=job_id,
            ),
        )

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
    ):
        if source != "regex":
            raise HTTPException(status_code=400, detail="Le deplacement progressif est disponible pour les regex Thunderbird.")
        if confirm_move != "yes" or confirm_thunderbird_closed != "yes":
            raise HTTPException(status_code=400, detail="Confirmation obligatoire et Thunderbird doit etre ferme avant l'action.")

        job_context = _regex_job_move_context(regex_job_id) if regex_job_id else None
        if job_context is None:
            raise HTTPException(status_code=400, detail="Le resultat du scan n'est plus disponible. Relance un scan regex avant de deplacer.")
        safe_uids, scan_report, regex_rules, min_age_days, max_mails = job_context
        if not safe_uids:
            raise HTTPException(status_code=400, detail="Le scan termine ne contient aucun candidat a deplacer.")

        move_job = CleanerMoveJob(
            id=uuid.uuid4().hex,
            total_count=len(safe_uids),
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
                moved_count, report = move_scanned_regex_uids_to_trash(
                    settings,
                    uids=safe_uids,
                    min_age_days=min_age_days,
                    progress_callback=progress,
                )
                report.scanned_count = scan_report.scanned_count
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
                        source="regex",
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
                        source="regex",
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
                source="regex",
                regex_rules=regex_rules,
                moved_count=job.moved_count,
                moved_destination="corbeille Thunderbird",
            ),
        )

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
                "offer_links": extract_offer_links(offer.body_text, offer.body_html),
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
        stats = run_pipeline(settings=settings)
        return RedirectResponse(
            url=f"/?refreshed=1&new={stats.new}&jobs={stats.job_related}",
            status_code=303,
        )

    return app


app = create_app()
