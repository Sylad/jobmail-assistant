from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..db import all_known_technos, connect, get_offer, init_db, list_offers, update_status
from ..models import OfferStatus
from ..pipeline import run as run_pipeline

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
        min_score: int = Query(0, ge=0, le=10),
    ):
        with connect(settings.db_path) as conn:
            status_filter = OfferStatus(status) if status else None
            offers = list_offers(conn, status=status_filter, techno=techno, min_score=min_score)
            technos = all_known_technos(conn)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "offers": offers,
                "technos": technos,
                "all_statuses": [s.value for s in OfferStatus],
                "current_status": status or "",
                "current_techno": techno or "",
                "current_min_score": min_score,
                "provider": settings.llm_provider,
                "imap_enabled": settings.imap_enabled,
            },
        )

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
    def set_status(offer_id: int, status: str = Form(...)):
        try:
            new_status = OfferStatus(status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        with connect(settings.db_path) as conn:
            if get_offer(conn, offer_id) is None:
                raise HTTPException(status_code=404, detail="Offer not found")
            update_status(conn, offer_id, new_status)
        return RedirectResponse(url=f"/offers/{offer_id}", status_code=303)

    @app.post("/refresh")
    def refresh():
        stats = run_pipeline(settings=settings)
        return RedirectResponse(
            url=f"/?refreshed=1&new={stats.new}&jobs={stats.job_related}",
            status_code=303,
        )

    return app


app = create_app()
