from __future__ import annotations

import time

from fastapi.testclient import TestClient

from jobmail.pipeline import PipelineStats
from jobmail.web import app as web_app


def _client(monkeypatch, tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    settings.llm_provider = "mock"
    settings.imap_host = ""
    settings.imap_user = ""
    settings.imap_password = ""
    settings.cleaner_mbox_globs = "/fake/Thunderbird/Profile/Mail/pop.gmail.com/Inbox"
    web_app._refresh_job = None
    return TestClient(web_app.create_app())


def test_refresh_uses_thunderbird_mbox_source(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    expected_source = iter(())

    def fake_resolve(patterns):
        captured["patterns"] = list(patterns)
        return ["/fake/Thunderbird/Profile/Mail/pop.gmail.com/Inbox"]

    def fake_build(paths, since_days=None, *, settings=None):
        captured["paths"] = paths
        captured["since_days"] = since_days
        captured["settings"] = settings
        return expected_source

    def fake_run_pipeline(source=None, *, settings=None, dry_run=None):
        captured["source"] = source
        captured["pipeline_settings"] = settings
        captured["dry_run"] = dry_run
        return PipelineStats(new=2, job_related=1)

    monkeypatch.setattr(web_app, "resolve_mbox_paths", fake_resolve)
    monkeypatch.setattr(web_app, "build_mbox_source", fake_build)
    monkeypatch.setattr(web_app, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(web_app, "_extract_pending_job_offers", lambda _settings, *, limit: (0, 0))

    client = _client(monkeypatch, tmp_path)
    resp = client.post("/refresh/start")

    assert resp.status_code == 200
    for _ in range(20):
        payload = client.get("/refresh/status").json()
        if payload["status"] == "done":
            break
        time.sleep(0.01)
    assert payload["status"] == "done"
    assert payload["new_count"] == 2
    assert payload["job_related_count"] == 1
    assert payload["extracted_count"] == 0
    assert payload["extraction_failed_count"] == 0
    assert captured["patterns"] == ["/fake/Thunderbird/Profile/Mail/pop.gmail.com/Inbox"]
    assert captured["paths"] == ["/fake/Thunderbird/Profile/Mail/pop.gmail.com/Inbox"]
    assert captured["source"] is expected_source


def test_refresh_form_starts_background_job(monkeypatch, tmp_path):
    started = {}

    def fake_start_refresh_job(settings):
        started["settings"] = settings
        return web_app.RefreshJob(id="job-1")

    monkeypatch.setattr(web_app, "_start_refresh_job", fake_start_refresh_job)

    client = _client(monkeypatch, tmp_path)
    resp = client.post("/refresh", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?refreshing=1"
    assert started["settings"] is web_app.get_settings()


def test_refresh_status_falls_back_to_default_pipeline_when_no_mbox(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_run_pipeline(source=None, *, settings=None, dry_run=None):
        captured["source"] = source
        captured["settings"] = settings
        return PipelineStats(new=0, job_related=0)

    monkeypatch.setattr(web_app, "resolve_mbox_paths", lambda _patterns: [])
    monkeypatch.setattr(web_app, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(web_app, "_extract_pending_job_offers", lambda _settings, *, limit: (0, 0))

    settings = web_app.get_settings()
    job = web_app.RefreshJob(id="job-1")
    web_app._run_refresh_job(settings, job)

    assert job.status == "done"
    assert captured["source"] is None


def test_refresh_start_reports_background_status(monkeypatch, tmp_path):
    def fake_run_refresh_job(_settings, job):
        time.sleep(0.02)
        job.fetched_count = 3
        job.new_count = 2
        job.job_related_count = 1
        job.extracted_count = 1
        job.sent_to_llm_count = 1
        job.status = "done"
        job.finished_at = time.time()

    monkeypatch.setattr(web_app, "_run_refresh_job", fake_run_refresh_job)

    client = _client(monkeypatch, tmp_path)
    start = client.post("/refresh/start").json()

    assert start["status"] == "running"
    for _ in range(20):
        status = client.get("/refresh/status").json()
        if status["status"] == "done":
            break
        time.sleep(0.01)

    assert status["status"] == "done"
    assert status["new_count"] == 2
    assert status["job_related_count"] == 1
    assert status["extracted_count"] == 1
    assert status["extraction_failed_count"] == 0


def test_refresh_status_reports_llm_extraction_failures(monkeypatch, tmp_path):
    def fake_run_refresh_job(_settings, job):
        job.new_count = 4
        job.job_related_count = 3
        job.sent_to_llm_count = 3
        job.extracted_count = 1
        job.status = "done"
        job.finished_at = time.time()

    monkeypatch.setattr(web_app, "_run_refresh_job", fake_run_refresh_job)

    client = _client(monkeypatch, tmp_path)
    client.post("/refresh/start")
    status = client.get("/refresh/status").json()

    assert status["status"] == "done"
    assert status["extraction_failed_count"] == 2


def test_refresh_status_includes_pending_extraction_retry(monkeypatch, tmp_path):
    def fake_run_pipeline(source=None, *, settings=None, dry_run=None):
        return PipelineStats(new=0, job_related=0, extracted=0, sent_to_llm=0)

    monkeypatch.setattr(web_app, "resolve_mbox_paths", lambda _patterns: [])
    monkeypatch.setattr(web_app, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(web_app, "_extract_pending_job_offers", lambda _settings, *, limit: (4, 3))

    client = _client(monkeypatch, tmp_path)
    client.post("/refresh/start")

    for _ in range(20):
        status = client.get("/refresh/status").json()
        if status["status"] == "done":
            break
        time.sleep(0.01)

    assert status["status"] == "done"
    assert status["sent_to_llm_count"] == 4
    assert status["extracted_count"] == 3
    assert status["extraction_failed_count"] == 1
