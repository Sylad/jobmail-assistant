from __future__ import annotations

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

    client = _client(monkeypatch, tmp_path)
    resp = client.post("/refresh", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?refreshed=1&new=2&jobs=1"
    assert captured["patterns"] == ["/fake/Thunderbird/Profile/Mail/pop.gmail.com/Inbox"]
    assert captured["paths"] == ["/fake/Thunderbird/Profile/Mail/pop.gmail.com/Inbox"]
    assert captured["source"] is expected_source


def test_refresh_falls_back_to_default_pipeline_when_no_mbox(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_run_pipeline(source=None, *, settings=None, dry_run=None):
        captured["source"] = source
        captured["settings"] = settings
        return PipelineStats(new=0, job_related=0)

    monkeypatch.setattr(web_app, "resolve_mbox_paths", lambda _patterns: [])
    monkeypatch.setattr(web_app, "run_pipeline", fake_run_pipeline)

    client = _client(monkeypatch, tmp_path)
    resp = client.post("/refresh", follow_redirects=False)

    assert resp.status_code == 303
    assert captured["source"] is None
