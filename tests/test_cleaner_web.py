from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from jobmail.cleaner import CleanerBackupCleanup, CleanerBackupSummary, CleanerTempCleanup, CleanerTempSummary
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
    settings.cleaner_backup_retention_days = 7
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
    assert "Mailbox cleaner" in resp.text
    assert "Backups Thunderbird" in resp.text
    assert "Nettoyer les anciens backups" in resp.text
    assert "js-pending-form" in resp.text
    assert 'data-pending-label="Nettoyage en cours..."' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'id="cleaner-vue-root"' in resp.text
    assert "data-initial" in resp.text
    assert '"source": "thunderbird"' in resp.text
    assert '<link rel="stylesheet" href="/static/assets/cleaner.css?v=' in resp.text
    assert '<script type="module" src="/static/assets/cleaner.js?v=' in resp.text
    assert "createApp" not in resp.text


def test_cleaner_backup_cleanup_requires_confirmation(monkeypatch, tmp_path):
    def fail_cleanup(*args, **kwargs):
        raise AssertionError("cleanup must not run without confirmation")

    monkeypatch.setattr(web_app, "delete_old_cleaner_backups", fail_cleanup)
    client = _client(monkeypatch, tmp_path)

    resp = client.post("/cleaner/backups/cleanup", data={"retention_days": "7"})

    assert resp.status_code == 400
    assert "Confirmation obligatoire" in resp.text


def test_cleaner_backup_cleanup_runs_after_confirmation(monkeypatch, tmp_path):
    calls = {}

    def fake_cleanup(settings, *, retention_days):
        calls["retention_days"] = retention_days
        return CleanerBackupCleanup(
            deleted_count=2,
            deleted_bytes=2048,
            summary=CleanerBackupSummary(retention_days=retention_days),
        )

    monkeypatch.setattr(web_app, "delete_old_cleaner_backups", fake_cleanup)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/backups/cleanup",
        data={"retention_days": "14", "confirm_cleanup": "yes"},
    )

    assert resp.status_code == 200
    assert calls == {"retention_days": 14}
    assert "2 backup(s) supprime(s)" in resp.text
    assert "2.0 KB liberes" in resp.text


def test_cleaner_temp_cleanup_requires_confirmation(monkeypatch, tmp_path):
    def fail_cleanup(*args, **kwargs):
        raise AssertionError("temp cleanup must not run without confirmation")

    monkeypatch.setattr(web_app, "move_orphan_cleaner_temp_files", fail_cleanup)
    client = _client(monkeypatch, tmp_path)

    resp = client.post("/cleaner/temp/cleanup")

    assert resp.status_code == 400
    assert "Confirmation obligatoire" in resp.text


def test_cleaner_temp_cleanup_runs_after_confirmation(monkeypatch, tmp_path):
    calls = {}

    def fake_cleanup(settings, *, destination_root):
        calls["destination_root"] = destination_root
        return CleanerTempCleanup(
            moved_count=2,
            moved_bytes=2048,
            destination=tmp_path / "moved-temp",
            summary=CleanerTempSummary(),
        )

    monkeypatch.setattr(web_app, "move_orphan_cleaner_temp_files", fake_cleanup)
    client = _client(monkeypatch, tmp_path)

    resp = client.post("/cleaner/temp/cleanup", data={"confirm_temp_cleanup": "yes"})

    assert resp.status_code == 200
    assert calls["destination_root"].name == "JobMail-Thunderbird-Backups"
    assert "2 temporaire(s) deplace(s)" in resp.text


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
    assert "store-news@amazon.fr" in resp.text
    assert "promo" in resp.text


def test_cleaner_regex_rules_can_be_saved_without_scan(monkeypatch, tmp_path):
    settings = web_app.get_settings()
    settings.cleaner_regex_rules_path = tmp_path / "cleaner-regex-rules.json"
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/regex-rules",
        json={
            "rules": [
                {"sender_regex": " store-news@amazon.fr ", "subject_regex": " promo "},
                {"sender_regex": "", "subject_regex": ""},
            ]
        },
    )

    assert resp.status_code == 200
    assert resp.json()["saved"] is True
    saved = settings.cleaner_regex_rules_path.read_text(encoding="utf-8")
    assert "store-news@amazon.fr" in saved
    assert "promo" in saved


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
    assert 'id="cleaner-vue-root"' in resp.text


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
    assert 'id="cleaner-vue-root"' in resp.text


def test_cleaner_regex_scan_progress_endpoints(monkeypatch, tmp_path):
    def fake_scan(
        settings,
        *,
        sender_regex,
        subject_regex,
        regex_rules,
        min_age_days,
        max_mails,
        progress_callback,
        should_cancel,
    ):
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

    result = client.get(f"/cleaner/scan/result-json/{job_id}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["report"]["candidates"][0]["subject"] == "Promo"
    assert payload["regex_rules"][0]["sender_regex"] == "amazon"


def test_cleaner_main_scan_progress_endpoints(monkeypatch, tmp_path):
    calls = {}

    def fake_scan(
        settings,
        *,
        min_age_days,
        max_mails,
        skip_mails,
        progress_callback,
        should_cancel,
    ):
        calls["args"] = {"min_age_days": min_age_days, "max_mails": max_mails, "skip_mails": skip_mails}
        progress_callback(CleanerReport(scanned_count=250, candidates=[]), "pop.example")
        return _report()

    monkeypatch.setattr(web_app, "scan_thunderbird_promotions", fake_scan)
    client = _client(monkeypatch, tmp_path)

    start = client.post(
        "/cleaner/scan/start",
        data={
            "source": "thunderbird",
            "min_age_days": "7",
            "max_mails": "0",
            "scan_offset": "1000",
        },
    )

    assert start.status_code == 200
    assert start.json()["status"] in {"running", "done"}
    job_id = start.json()["id"]
    for _ in range(20):
        payload = client.get(f"/cleaner/scan/status/{job_id}").json()
        if payload["status"] == "done":
            break
    assert payload["status"] == "done"
    assert payload["scanned_count"] == 3
    assert payload["candidate_count"] == 1
    assert calls["args"] == {"min_age_days": 7, "max_mails": 0, "skip_mails": 1000}

    result = client.get(f"/cleaner/scan/result-json/{job_id}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["report"]["candidates"][0]["subject"] == "Promos anciennes"
    assert payload["scan_offset"] == 1000


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
    assert 'id="cleaner-vue-root"' in resp.text


def test_cleaner_jobs_page_selects_parsed_jobs_source(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.get("/cleaner/jobs")

    assert resp.status_code == 200
    assert '"source": "parsed_jobs"' in resp.text


def test_cleaner_duplicates_page_selects_duplicates_source(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.get("/cleaner/duplicates")

    assert resp.status_code == 200
    assert '"source": "duplicates"' in resp.text


def test_cleaner_duplicates_scan_uses_dedicated_source(monkeypatch, tmp_path):
    calls = {}

    def fake_scan(settings, *, min_age_days, max_mails):
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        return CleanerReport(
            scanned_count=2,
            candidates=[
                CleanerCandidate(
                    uid="mbox:pop.orange.fr:0",
                    received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    sender="sender@example.com",
                    subject="Doublon",
                    reason="doublon Message-Id present dans pop.gmail.com",
                    source="mbox",
                    mailbox="pop.orange.fr",
                    duplicate_of="pop.gmail.com:<dup@local>",
                )
            ],
        )

    monkeypatch.setattr(web_app, "scan_thunderbird_duplicates", fake_scan)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/scan",
        data={"source": "duplicates", "min_age_days": "7", "max_mails": "1000"},
    )

    assert resp.status_code == 200
    assert calls == {"min_age_days": 7, "max_mails": 1000}
    assert 'id="cleaner-vue-root"' in resp.text


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


def test_cleaner_duplicates_move_calls_dedicated_service(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, uids, min_age_days):
        calls["uids"] = uids
        calls["min_age_days"] = min_age_days
        return 1, _report()

    monkeypatch.setattr(web_app, "move_thunderbird_duplicates_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={
            "source": "duplicates",
            "selected_uid": "mbox:pop.orange.fr:0",
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
            "min_age_days": "9",
            "max_mails": "12",
        },
    )

    assert resp.status_code == 200
    assert calls == {"uids": ["mbox:pop.orange.fr:0"], "min_age_days": 9}


def test_cleaner_regex_move_reuses_finished_scan_job(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, uids, min_age_days):
        calls["uids"] = uids
        calls["min_age_days"] = min_age_days
        return 2, _report()

    monkeypatch.setattr(web_app, "move_scanned_regex_uids_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)
    job = web_app.CleanerScanJob(
        id="job-123",
        status="done",
        scanned_count=12,
        candidate_count=1,
        report=CleanerReport(
            scanned_count=12,
            candidates=[
                CleanerCandidate(
                    uid="mbox:pop.example:123",
                    received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    sender="amazon@example.com",
                    subject="Promo",
                    reason="regle 1",
                    source="mbox",
                )
            ],
        ),
        min_age_days=9,
        max_mails=0,
        regex_rules=[("amazon", "promo")],
    )
    with web_app._cleaner_jobs_lock:
        web_app._cleaner_jobs[job.id] = job

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={
            "source": "regex",
            "regex_job_id": "job-123",
            "sender_regex_rule": ["amazon", "googleplay"],
            "subject_regex_rule": ["promo", ""],
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
        },
    )

    assert resp.status_code == 200
    assert calls == {"uids": ["mbox:pop.example:123"], "min_age_days": 9}
    assert "2 mail(s) deplace(s)" in resp.text


def test_cleaner_regex_move_progress_endpoints(monkeypatch, tmp_path):
    def fake_move(settings, *, uids, min_age_days, progress_callback):
        progress_callback(1)
        return 1, CleanerReport(
            scanned_count=12,
            candidates=[
                CleanerCandidate(
                    uid=uids[0],
                    received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    sender="amazon@example.com",
                    subject="Promo",
                    reason="regle 1",
                    source="mbox",
                )
            ],
        )

    monkeypatch.setattr(web_app, "move_scanned_regex_uids_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)
    scan_job = web_app.CleanerScanJob(
        id="scan-job-456",
        status="done",
        scanned_count=12,
        candidate_count=1,
        report=CleanerReport(
            scanned_count=12,
            candidates=[
                CleanerCandidate(
                    uid="mbox:pop.example:456",
                    received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    sender="amazon@example.com",
                    subject="Promo",
                    reason="regle 1",
                    source="mbox",
                )
            ],
        ),
        min_age_days=9,
        max_mails=0,
        regex_rules=[("amazon", "promo")],
    )
    with web_app._cleaner_jobs_lock:
        web_app._cleaner_jobs[scan_job.id] = scan_job

    start = client.post(
        "/cleaner/move-thunderbird-to-trash/start",
        data={
            "source": "regex",
            "regex_job_id": "scan-job-456",
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
        },
    )

    assert start.status_code == 200
    move_job_id = start.json()["id"]
    for _ in range(20):
        payload = client.get(f"/cleaner/move/status/{move_job_id}").json()
        if payload["status"] == "done":
            break
    assert payload["status"] == "done"
    assert payload["total_count"] == 1
    assert payload["moved_count"] == 1

    result = client.get(f"/cleaner/move/status/{move_job_id}/result")
    assert result.status_code == 200
    assert "1 mail(s) deplace(s)" in result.text
    assert "corbeille Thunderbird" in result.text


def test_cleaner_mbox_move_progress_endpoints(monkeypatch, tmp_path):
    calls = {}

    def fake_move(settings, *, uids, min_age_days, max_mails, progress_callback):
        calls["uids"] = uids
        calls["min_age_days"] = min_age_days
        calls["max_mails"] = max_mails
        progress_callback(1)
        return 1, _report()

    monkeypatch.setattr(web_app, "move_thunderbird_to_trash", fake_move)
    client = _client(monkeypatch, tmp_path)

    start = client.post(
        "/cleaner/move-thunderbird-to-trash/start",
        data={
            "source": "thunderbird",
            "selected_uid": "mbox:pop.example:123",
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
            "min_age_days": "9",
            "max_mails": "12",
        },
    )

    assert start.status_code == 200
    move_job_id = start.json()["id"]
    for _ in range(20):
        payload = client.get(f"/cleaner/move/status/{move_job_id}").json()
        if payload["status"] == "done":
            break
    assert payload["status"] == "done"
    assert payload["total_count"] == 1
    assert payload["moved_count"] == 1
    assert payload["result_json_url"] == f"/cleaner/move/status/{move_job_id}/result-json"
    assert calls == {"uids": ["mbox:pop.example:123"], "min_age_days": 9, "max_mails": 12}

    result = client.get(f"/cleaner/move/status/{move_job_id}/result-json")
    assert result.status_code == 200
    assert result.json()["source"] == "thunderbird"
    assert result.json()["moved_count"] == 1


def test_cleaner_regex_move_requires_finished_scan_job(monkeypatch, tmp_path):
    def fail_move(*args, **kwargs):
        raise AssertionError("move must not run without a finished scan job")

    monkeypatch.setattr(web_app, "move_scanned_regex_uids_to_trash", fail_move)
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/cleaner/move-thunderbird-to-trash",
        data={
            "source": "regex",
            "sender_regex_rule": "amazon",
            "subject_regex_rule": "promo",
            "confirm_move": "yes",
            "confirm_thunderbird_closed": "yes",
        },
    )

    assert resp.status_code == 400
    assert "Relance un scan regex" in resp.text
