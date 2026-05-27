from __future__ import annotations

import time
from datetime import datetime

from fastapi.testclient import TestClient

from jobmail.db import connect, insert_email
from jobmail.models import RawEmail
from jobmail.web import app as web_app


def _client(tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    settings.llm_provider = "mock"
    web_app._reanalysis_job = None
    return TestClient(web_app.create_app())


def test_dashboard_renders_reanalysis_panel(tmp_path):
    client = _client(tmp_path)

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Ré-analyser avec Ollama" in resp.text
    assert "/offers/reanalyze/start" in resp.text


def test_reanalysis_job_updates_cached_job_offer(tmp_path):
    client = _client(tmp_path)
    settings = web_app.get_settings()
    email = RawEmail(
        uid="mail-1",
        message_id="<mail-1@local>",
        subject="Mission Java GeoServer",
        sender="recruiter@example.com",
        received_at=datetime(2026, 5, 25, 9, 30),
        body_text="Mission Java GeoServer PostGIS CDI à Toulouse. https://jobs.example.com/42",
    )
    with connect(settings.db_path) as conn:
        insert_email(conn, email, job_related=True, matched_keywords=["mission", "java"])

    resp = client.post("/offers/reanalyze/start")

    assert resp.status_code == 200
    for _ in range(50):
        status = client.get("/offers/reanalyze/status").json()
        if status["status"] == "done":
            break
        time.sleep(0.02)

    assert status["status"] == "done"
    assert status["updated_count"] == 1
    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT title, offer_url FROM offers WHERE email_uid = ?", (email.uid,)).fetchone()
    assert row["title"] == "Mission Java GeoServer"
    assert row["offer_url"] == "https://jobs.example.com/42"
