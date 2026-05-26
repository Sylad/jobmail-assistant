from __future__ import annotations

import sqlite3
import csv
import io
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..cleaner import (
    CleanerError,
    CleanerReport,
    move_parsed_jobs_to_trash,
    move_thunderbird_to_trash,
    move_to_delete,
    scan_parsed_job_mails,
    scan_old_promotions,
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


def _cleaner_context(
    *,
    request: Request,
    settings,
    report: CleanerReport | None = None,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    source: str = "thunderbird",
    error: str = "",
    moved_count: int = 0,
) -> dict:
    return {
        "request": request,
        "report": report,
        "min_age_days": min_age_days or settings.cleaner_min_age_days,
        "max_mails": max_mails or settings.cleaner_max_mails,
        "source": source,
        "delete_folder": settings.cleaner_delete_folder,
        "mbox_patterns": settings.cleaner_mbox_patterns,
        "error": error,
        "moved_count": moved_count,
        "provider": settings.llm_provider,
        "imap_enabled": settings.imap_enabled,
    }


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

    @app.get("/cleaner/jobs", response_class=HTMLResponse)
    def cleaner_jobs(request: Request):
        return templates.TemplateResponse(
            request,
            "cleaner.html",
            _cleaner_context(request=request, settings=settings, source="parsed_jobs"),
        )

    @app.post("/cleaner/scan", response_class=HTMLResponse)
    def cleaner_scan(
        request: Request,
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
        source: str = Form("thunderbird"),
        export_csv: str = Form(""),
    ):
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
            else:
                source = "thunderbird"
                report = scan_thunderbird_promotions(
                    settings,
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
                source=source,
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

    @app.post("/cleaner/move-thunderbird-to-trash", response_class=HTMLResponse)
    def cleaner_move_thunderbird_to_trash(
        request: Request,
        min_age_days: int = Form(settings.cleaner_min_age_days),
        max_mails: int = Form(settings.cleaner_max_mails),
        selected_uid: list[str] = Form(default=[]),
        confirm_move: str = Form(""),
        confirm_thunderbird_closed: str = Form(""),
        source: str = Form("thunderbird"),
    ):
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
