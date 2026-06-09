from __future__ import annotations

from fastapi.testclient import TestClient

from jobmail.cleaner.models import CleanerCandidate, CleanerReport
from jobmail.pipeline import PipelineStats
from jobmail.web import app as web_app


def _client(tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    settings.llm_provider = "mock"
    settings.imap_host = ""
    settings.imap_user = ""
    settings.imap_password = ""
    return TestClient(web_app.create_app())


def test_thunderbird_import_converts_messages_to_pipeline_source(monkeypatch, tmp_path):
    captured = {}

    def fake_run_pipeline(source=None, *, settings=None, dry_run=None):
        emails = list(source)
        captured["emails"] = emails
        captured["settings"] = settings
        captured["dry_run"] = dry_run
        return PipelineStats(
            fetched=len(emails),
            new=1,
            job_related=1,
            extracted=1,
            sent_to_llm=1,
        )

    monkeypatch.setattr(web_app, "run_pipeline", fake_run_pipeline)

    client = _client(tmp_path)
    response = client.post(
        "/api/thunderbird/import",
        json={
            "messages": [
                {
                    "id": 42,
                    "messageId": "<offer@example.test>",
                    "subject": "Developpeur Python",
                    "author": "Recruiter <recruiter@example.test>",
                    "date": "2026-06-09T08:30:00Z",
                    "bodyPlain": "Bonjour, mission Python FastAPI remote.",
                    "folderAccount": "account11",
                    "folderPath": "/Inbox",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["job_related_count"] == 1
    assert len(captured["emails"]) == 1
    email = captured["emails"][0]
    assert email.uid.startswith("thunderbird:")
    assert email.message_id == "<offer@example.test>"
    assert email.subject == "Developpeur Python"
    assert email.sender == "Recruiter <recruiter@example.test>"
    assert email.body_text == "Bonjour, mission Python FastAPI remote."
    assert email.mbox_path == ""
    assert email.mbox_offset == -1


def test_thunderbird_import_rejects_invalid_payload(tmp_path):
    client = _client(tmp_path)
    response = client.post("/api/thunderbird/import", json={"messages": "nope"})

    assert response.status_code == 400


def test_thunderbird_cleaner_scan_returns_candidates(tmp_path):
    client = _client(tmp_path)
    response = client.post(
        "/api/thunderbird/cleaner/scan",
        json={
            "minAgeDays": 7,
            "messages": [
                {
                    "id": 123,
                    "messageId": "<promo@example.test>",
                    "subject": "Derniere chance promotion",
                    "author": "newsletter@example.test",
                    "date": "2026-05-01T08:30:00Z",
                    "bodyPlain": "Cliquez pour vous desabonner.",
                    "hasAttachment": False,
                },
                {
                    "id": 124,
                    "subject": "Facture",
                    "author": "billing@example.test",
                    "date": "2026-05-01T08:30:00Z",
                    "bodyPlain": "Votre facture est disponible.",
                    "hasAttachment": True,
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scanned_count"] == 2
    assert payload["candidate_count"] == 1
    assert payload["skipped_safety"] == 1
    assert payload["candidates"][0]["id"] == 123
    assert payload["candidates"][0]["reason"]


def test_thunderbird_bridge_event_updates_status(tmp_path):
    client = _client(tmp_path)
    response = client.post(
        "/api/thunderbird/bridge/event",
        json={
            "event": "cleaner_move",
            "payload": {"requested_count": 15, "resolved_count": 12, "moved_count": 12},
        },
    )

    assert response.status_code == 200
    assert response.json()["last_cleaner_moved_count"] == 12
    assert response.json()["last_cleaner_requested_count"] == 15
    assert response.json()["last_cleaner_resolved_count"] == 12

    status = client.get("/api/status").json()
    assert status["thunderbird"]["last_cleaner_moved_count"] == 12


def test_thunderbird_latest_cleaner_request_exposes_done_scan(tmp_path):
    client = _client(tmp_path)
    job = web_app.CleanerScanJob(id="scan-1", source="thunderbird")
    job.status = "done"
    job.finished_at = 1_800_000_000
    job.report = CleanerReport(
        scanned_count=1,
        candidates=[
            CleanerCandidate(
                uid="mbox:pop.orange.fr:123",
                received_at=web_app.datetime.fromisoformat("2026-05-01T08:30:00"),
                sender="newsletter@example.test",
                subject="Promotion",
                reason="expediteur promotionnel",
                message_id="<promo@example.test>",
                source="mbox",
                mailbox="pop.orange.fr",
            )
        ],
    )
    with web_app._cleaner_jobs_lock:
        web_app._cleaner_jobs.clear()
        web_app._cleaner_jobs[job.id] = job

    response = client.get("/api/thunderbird/cleaner/latest-request")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["message_id"] == "<promo@example.test>"
