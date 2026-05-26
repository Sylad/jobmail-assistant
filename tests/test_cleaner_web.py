from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from jobmail.cleaner.models import CleanerCandidate, CleanerReport
from jobmail.web import app as web_app


def _client(monkeypatch, tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    settings.imap_host = "imap.example.com"
    settings.imap_user = "user"
    settings.imap_password = "pass"
    settings.cleaner_min_age_days = 7
    settings.cleaner_max_mails = 25
    return TestClient(web_app.create_app())


def _report() -> CleanerReport:
    return CleanerReport(
        scanned_count=3,
        candidates=[
            CleanerCandidate(
                uid="101",
                received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                sender="newsletter@example.com",
                subject="Promos anciennes",
                reason="mot-cle promotionnel: newsletter",
            )
        ],
    )


def test_cleaner_page_renders(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.get("/cleaner")

    assert resp.status_code == 200
    assert "Scanner pubs anciennes" in resp.text
    assert "Mailbox cleaner" in resp.text


def test_cleaner_scan_renders_report(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "scan_old_promotions", lambda *args, **kwargs: _report())
    client = _client(monkeypatch, tmp_path)

    resp = client.post("/cleaner/scan", data={"min_age_days": "7", "max_mails": "20"})

    assert resp.status_code == 200
    assert "Mails scannes" in resp.text
    assert "Promos anciennes" in resp.text
    assert "Deplacer la selection" in resp.text


def test_cleaner_scan_exports_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "scan_old_promotions", lambda *args, **kwargs: _report())
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={"min_age_days": "7", "max_mails": "20", "export_csv": "1"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "newsletter@example.com" in resp.text


def test_cleaner_move_requires_confirmation(monkeypatch, tmp_path):
    def fail_move(*args, **kwargs):
        raise AssertionError("move_to_delete must not run without confirmation")

    monkeypatch.setattr(web_app, "move_to_delete", fail_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post("/cleaner/move-to-delete", data={"selected_uid": "101"})

    assert resp.status_code == 400
    assert "Confirmation obligatoire" in resp.text


def test_cleaner_move_calls_service_after_confirmation(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, uids, min_age_days, max_mails):
        calls["uids"] = uids
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return 1, _report()

    monkeypatch.setattr(web_app, "move_to_delete", fake_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-to-delete",
        data={
            "selected_uid": "101",
            "confirm_move": "yes",
            "min_age_days": "9",
            "max_mails": "12",
        },
    )

    assert resp.status_code == 200
    assert calls == {"uids": ["101"], "min_age_days": 9, "max_mails": 12}
    assert "1 mail(s) deplace(s)" in resp.text
