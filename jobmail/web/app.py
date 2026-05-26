from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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
        if "jobmail" in cmdline and (" fetch" in cmdline or " dry-run" in cmdline):
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


def _compute_stats(conn: sqlite3.Connection) -> dict:
    n_emails = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
    n_jobs = conn.execute("SELECT COUNT(*) FROM emails WHERE job_related=1").fetchone()[0]
    n_offers = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    last = conn.execute("SELECT MAX(created_at) FROM emails").fetchone()[0]
    last_extract = conn.execute("SELECT MAX(extracted_at) FROM offers").fetchone()[0]

    is_running, pid = _pipeline_process_active()
    uptime = _process_uptime(pid) if pid else None

    # Phase heuristic when running:
    #   - parsing : process alive but no emails yet
    #   - filtering : emails but no offers yet
    #   - extracting : offers being created
    phase = None
    if is_running:
        if n_emails == 0:
            phase = "Parsing MBOX (lecture initiale du fichier)"
        elif n_offers == 0:
            phase = "Classification locale en cours"
        else:
            phase = "Extraction LLM en cours"

    return {
        "emails": n_emails,
        "jobs": n_jobs,
        "offers": n_offers,
        "is_running": is_running,
        "pid": pid,
        "uptime": uptime,
        "phase": phase,
        "last_activity": last_extract or last,
    }

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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

    @app.get("/offers/{offer_id}", response_class=HTMLResponse)
    def offer_detail(request: Request, offer_id: int):
        with connect(settings.db_path) as conn:
            offer = get_offer(conn, offer_id)
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")
        return templates.TemplateResponse(
            request,
            "offer.html",
            {
                "offer": offer,
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
