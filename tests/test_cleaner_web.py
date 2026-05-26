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
                offer_id=42,
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
    monkeypatch.setattr(web_app, "scan_thunderbird_promotions", lambda *args, **kwargs: _report())
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={"source": "thunderbird", "min_age_days": "7", "max_mails": "20"},
    )

    assert resp.status_code == 200
    assert "Mails scannes" in resp.text
    assert "Promos anciennes" in resp.text
    assert "Action Thunderbird locale" in resp.text
    assert "corbeille Thunderbird" in resp.text
    assert 'name="selected_uid" value="101" checked data-candidate-checkbox' in resp.text
    assert "Tout selectionner" in resp.text
    assert "Tout exclure" in resp.text
    assert 'data-sender-row="newsletter@example.com"' in resp.text
    assert "data-sender-state" in resp.text
    assert 'data-exclude-sender="newsletter@example.com"' in resp.text


def test_cleaner_scan_exports_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "scan_thunderbird_promotions", lambda *args, **kwargs: _report())
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={"source": "thunderbird", "min_age_days": "7", "max_mails": "20", "export_csv": "1"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "newsletter@example.com" in resp.text
    assert "source_path" in resp.text


def test_cleaner_parsed_jobs_scan_uses_dedicated_source(monkeypatch, tmp_path):
    calls = {}

    def fake_scan(settings, *, min_age_days, max_mails):
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return _report()

    monkeypatch.setattr(web_app, "scan_parsed_job_mails", fake_scan)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={"source": "parsed_jobs", "min_age_days": "15", "max_mails": "20"},
    )

    assert resp.status_code == 200
    assert calls == {"min_age_days": 15, "max_mails": 20}
    assert "offre <code>ignored</code>" in resp.text
    assert "offres <code>interesting</code> et <code>replied</code> sont protegees" in resp.text
    assert "/offers/42" in resp.text


def test_cleaner_jobs_page_selects_parsed_jobs_source(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.get("/cleaner/jobs")

    assert resp.status_code == 200
    assert 'value="parsed_jobs" selected' in resp.text
    assert "Scanner jobs nettoyables" in resp.text


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


def test_cleaner_mbox_move_requires_both_confirmations(monkeypatch, tmp_path):
    def fail_move(*args, **kwargs):
        raise AssertionError("move_thunderbird_to_trash must not run without confirmations")

    monkeypatch.setattr(web_app, "move_thunderbird_to_trash", fail_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={"selected_uid": "mbox:pop.example:0", "confirm_move": "yes"},
    )

    assert resp.status_code == 400
    assert "Thunderbird doit etre ferme" in resp.text


def test_cleaner_mbox_move_calls_service_after_confirmations(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, uids, min_age_days, max_mails):
        calls["uids"] = uids
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return 1, _report()

    monkeypatch.setattr(web_app, "move_thunderbird_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={
            "selected_uid": "mbox:pop.example:0",
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
            "min_age_days": "9",
            "max_mails": "12",
        },
    )

    assert resp.status_code == 200
    assert calls == {"uids": ["mbox:pop.example:0"], "min_age_days": 9, "max_mails": 12}
    assert "1 mail(s) deplace(s)" in resp.text


def test_cleaner_parsed_jobs_move_calls_dedicated_service(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, uids, min_age_days, max_mails):
        calls["uids"] = uids
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return 1, _report()

    monkeypatch.setattr(web_app, "move_parsed_jobs_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={
            "source": "parsed_jobs",
            "selected_uid": "mbox:pop.example:0",
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
            "min_age_days": "9",
            "max_mails": "12",
        },
    )

    assert resp.status_code == 200
    assert calls == {"uids": ["mbox:pop.example:0"], "min_age_days": 9, "max_mails": 12}
