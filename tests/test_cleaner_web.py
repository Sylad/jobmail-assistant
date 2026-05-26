from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from jobmail.cleaner.models import CleanerCandidate, CleanerReport
from jobmail.web import app as web_app


def _client(monkeypatch, tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    settings.cleaner_regex_rules_path = tmp_path / "cleaner-regex-rules.json"
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
    assert '<input type="hidden" name="source" value="regex">' in resp.text
    regex_form = '<form method="post" action="/cleaner/scan" class="filter-form" data-regex-scan-form>'
    assert resp.text.count(regex_form) == 1
    assert '<button type="button" class="btn btn-primary" data-start-regex-scan>Scanner toute la boite par regex</button>' in resp.text


def test_cleaner_page_loads_saved_regex_rules(monkeypatch, tmp_path):
    settings = web_app.get_settings()
    settings.cleaner_regex_rules_path = tmp_path / "cleaner-regex-rules.json"
    settings.cleaner_regex_rules_path.write_text(
        '{"rules":[{"sender_regex":"store-news@amazon.fr","subject_regex":"promo"}]}',
        encoding="utf-8",
    )
    client = _client(monkeypatch, tmp_path)

    resp = client.get("/cleaner")

    assert resp.status_code == 200
    assert 'name="sender_regex_rule" value="store-news@amazon.fr"' in resp.text
    assert 'name="subject_regex_rule" value="promo"' in resp.text


def test_cleaner_scan_renders_report(monkeypatch, tmp_path):
    calls = {}

    def fake_scan(settings, *, min_age_days, max_mails, skip_mails):
        calls["skip_mails"] = skip_mails
        return _report()

    monkeypatch.setattr(web_app, "scan_thunderbird_promotions", fake_scan)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={"source": "thunderbird", "min_age_days": "7", "max_mails": "20", "scan_offset": "1000"},
    )

    assert resp.status_code == 200
    assert calls == {"skip_mails": 1000}
    assert "Mails scannes" in resp.text
    assert "Mails ignores avant scan" in resp.text
    assert "Scanner les 20 suivants" in resp.text
    assert "Tranche actuelle : 1001 - 1003" in resp.text
    assert "Promos anciennes" in resp.text
    assert "Action Thunderbird locale" in resp.text
    assert "corbeille Thunderbird" in resp.text
    assert 'name="selected_uid" value="101" checked data-candidate-checkbox' in resp.text
    assert "Tout selectionner" in resp.text
    assert "Tout exclure" in resp.text
    assert 'data-sender-row="newsletter@example.com"' in resp.text
    assert "data-sender-state" in resp.text
    assert 'data-exclude-sender="newsletter@example.com"' in resp.text


def test_cleaner_regex_scan_renders_report(monkeypatch, tmp_path):
    calls = {}

    def fake_scan(settings, *, sender_regex, subject_regex, regex_rules, min_age_days, max_mails):
        calls["sender_regex"] = sender_regex
        calls["subject_regex"] = subject_regex
        calls["regex_rules"] = regex_rules
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return _report()

    monkeypatch.setattr(web_app, "scan_thunderbird_regex", fake_scan)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={
            "source": "regex",
            "sender_regex_rule": ["amazon", "googleplay"],
            "subject_regex_rule": ["recommande", "promo"],
            "min_age_days": "30",
            "max_mails": "0",
        },
    )

    assert resp.status_code == 200
    assert calls == {
        "sender_regex": "",
        "subject_regex": "",
        "regex_rules": [("amazon", "recommande"), ("googleplay", "promo")],
        "min_age_days": 30,
        "max_mails": 0,
    }
    assert "Scanner toute la boite par regex" in resp.text
    assert 'name="sender_regex_rule" value="amazon"' in resp.text
    assert 'name="subject_regex_rule" value="promo"' in resp.text
    assert "Deplacer tous les resultats regex vers la corbeille Thunderbird" in resp.text


def test_cleaner_regex_scan_progress_endpoints(monkeypatch, tmp_path):
    def fake_scan(settings, *, sender_regex, subject_regex, regex_rules, min_age_days, max_mails, progress_callback):
        report = CleanerReport(
            scanned_count=250,
            candidates=[
                CleanerCandidate(
                    uid="mbox:pop.example:0",
                    received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    sender="amazon@example.com",
                    subject="Promo",
                    reason="regle 1: regex expediteur: amazon",
                    source="mbox",
                )
            ],
        )
        progress_callback(CleanerReport(scanned_count=100, candidates=[]), "pop.example")
        return report

    monkeypatch.setattr(web_app, "scan_thunderbird_regex", fake_scan)
    client = _client(monkeypatch, tmp_path)

    start = client.post(
        "/cleaner/scan/start",
        data={
            "source": "regex",
            "sender_regex_rule": "amazon",
            "subject_regex_rule": "",
            "min_age_days": "30",
            "max_mails": "0",
        },
    )

    assert start.status_code == 200
    saved = web_app.get_settings().cleaner_regex_rules_path.read_text(encoding="utf-8")
    assert "amazon" in saved
    job_id = start.json()["id"]
    status = client.get(f"/cleaner/scan/status/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] in {"running", "done"}

    for _ in range(20):
        payload = client.get(f"/cleaner/scan/status/{job_id}").json()
        if payload["status"] == "done":
            break
    assert payload["status"] == "done"
    assert payload["scanned_count"] == 250
    assert payload["candidate_count"] == 1

    result = client.get(f"/cleaner/scan/result/{job_id}")
    assert result.status_code == 200
    assert "Promo" in result.text
    assert "Regles appliquees" in result.text


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


def test_cleaner_regex_move_replays_rules_after_confirmations(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, sender_regex, subject_regex, regex_rules, min_age_days, max_mails):
        calls["sender_regex"] = sender_regex
        calls["subject_regex"] = subject_regex
        calls["regex_rules"] = regex_rules
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return 2, _report()

    monkeypatch.setattr(web_app, "move_thunderbird_regex_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={
            "source": "regex",
            "sender_regex_rule": ["amazon", "googleplay"],
            "subject_regex_rule": ["promo", ""],
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
            "min_age_days": "9",
            "max_mails": "0",
        },
    )

    assert resp.status_code == 200
    assert calls == {
        "sender_regex": "",
        "subject_regex": "",
        "regex_rules": [("amazon", "promo"), ("googleplay", "")],
        "min_age_days": 9,
        "max_mails": 0,
    }
    assert "2 mail(s) deplace(s)" in resp.text
