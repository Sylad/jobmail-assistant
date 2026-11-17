from __future__ import annotations

import pytest
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


# ── L4/t5 : « Corbeille scan JobMail » ne reçoit que la sélection confirmée dans /cleaner ──


def _candidate(uid: str, message_id: str, *, can_move: bool = True, sender: str = "newsletter@example.test"):
    return CleanerCandidate(
        uid=uid,
        received_at=web_app.datetime.fromisoformat("2026-05-01T08:30:00"),
        sender=sender,
        subject=f"Promotion {uid}",
        reason="expediteur promotionnel",
        message_id=message_id,
        source="mbox" if can_move else "duplicate_reference",
        mailbox="pop.orange.fr",
    )


def _done_scan(job_id: str, source: str, candidates, *, finished_at: float = 1_800_000_000):
    job = web_app.CleanerScanJob(id=job_id, source=source)
    job.status = "done"
    job.finished_at = finished_at
    job.report = CleanerReport(scanned_count=len(candidates), candidates=list(candidates))
    return job


def _install_scans(*jobs):
    with web_app._cleaner_jobs_lock:
        web_app._cleaner_jobs.clear()
        for job in jobs:
            web_app._cleaner_jobs[job.id] = job
    web_app._clear_thunderbird_cleaner_request()


def _three_candidate_scans():
    _install_scans(
        _done_scan(
            "scan-regex",
            "regex",
            [_candidate("mbox:a:1", "<one@example.test>"), _candidate("mbox:a:2", "<two@example.test>")],
        ),
        _done_scan(
            "scan-old",
            "duplicates",
            [_candidate("mbox:a:3", "<three@example.test>"), _candidate("mbox:a:4", "<four@example.test>", can_move=False)],
            finished_at=1_700_000_000,
        ),
    )


def _confirm(client, uids, confirm="yes"):
    return client.post(
        "/api/thunderbird/cleaner/request",
        data={"selected_uid": uids, "confirm_move": confirm},
    )


def test_latest_cleaner_request_refuses_scans_without_confirmed_selection(tmp_path):
    # Avant t5 : tous les candidats de tous les scans terminés étaient servis à l'extension.
    client = _client(tmp_path)
    _three_candidate_scans()

    response = client.get("/api/thunderbird/cleaner/latest-request")

    assert response.status_code == 400
    assert response.json()["detail"] == web_app.NO_SELECTION_MESSAGE
    assert "candidates" not in response.json()


def test_latest_cleaner_request_serves_only_the_confirmed_selection(tmp_path):
    client = _client(tmp_path)
    _three_candidate_scans()

    confirmed = _confirm(client, ["mbox:a:2"])

    assert confirmed.status_code == 200
    assert confirmed.json()["candidate_count"] == 1
    payload = client.get("/api/thunderbird/cleaner/latest-request").json()
    assert payload["source"] == "confirmed_selection"
    assert payload["request_id"] == confirmed.json()["request_id"]
    assert payload["candidate_count"] == 1
    # L'expéditeur exclu (mbox:a:1) et le scan plus ancien (mbox:a:3) ne partent pas.
    assert [c["message_id"] for c in payload["candidates"]] == ["<two@example.test>"]


@pytest.mark.parametrize("uids", [[], [""], ["   ", "\t"]])
def test_cleaner_request_without_selection_is_refused_and_stores_nothing(tmp_path, uids):
    client = _client(tmp_path)
    _three_candidate_scans()

    response = _confirm(client, uids)

    assert response.status_code == 400
    assert response.json()["detail"] == web_app.NO_SELECTION_MESSAGE
    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 400


def test_cleaner_request_requires_the_confirmation(tmp_path):
    client = _client(tmp_path)
    _three_candidate_scans()

    response = _confirm(client, ["mbox:a:2"], confirm="")

    assert response.status_code == 400
    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 400


def test_cleaner_request_is_bounded_to_movable_scan_candidates(tmp_path):
    client = _client(tmp_path)
    _three_candidate_scans()

    # UID inconnu des scans et candidat non déplaçable : rien, pas « tout le scan ».
    assert _confirm(client, ["mbox:zzz:9", "mbox:a:4"]).status_code == 400
    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 400

    assert _confirm(client, ["mbox:zzz:9", "mbox:a:4", "mbox:a:3"]).status_code == 200
    payload = client.get("/api/thunderbird/cleaner/latest-request").json()
    assert [c["uid"] for c in payload["candidates"]] == ["mbox:a:3"]


def test_cleaner_request_ignores_imap_scans(tmp_path):
    client = _client(tmp_path)
    _install_scans(_done_scan("scan-imap", "imap", [_candidate("imap:1", "<imap@example.test>")]))

    assert _confirm(client, ["imap:1"]).status_code == 400


def test_a_refused_confirmation_cancels_the_previous_request(tmp_path):
    client = _client(tmp_path)
    _three_candidate_scans()
    assert _confirm(client, ["mbox:a:1"]).status_code == 200

    assert _confirm(client, []).status_code == 400

    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 400


def test_cleaner_request_is_consumed_as_soon_as_it_is_served(tmp_path):
    # Revue L4/t5, n1 : l'usage unique ne dépend plus du compte rendu de l'extension (qui peut
    # se perdre). Avant : la demande restait servie tant que `cleaner_move` n'était pas rapporté.
    client = _client(tmp_path)
    _three_candidate_scans()
    request_id = _confirm(client, ["mbox:a:1"]).json()["request_id"]

    first = client.get("/api/thunderbird/cleaner/latest-request")
    assert first.status_code == 200
    assert first.json()["request_id"] == request_id
    assert [c["uid"] for c in first.json()["candidates"]] == ["mbox:a:1"]

    # Aucun compte rendu de l'extension : un second clic ne rejoue pourtant pas la demande.
    second = client.get("/api/thunderbird/cleaner/latest-request")
    assert second.status_code == 400
    assert second.json()["detail"] == web_app.NO_SELECTION_MESSAGE


def test_a_served_request_can_only_be_replaced_by_a_new_confirmation(tmp_path):
    client = _client(tmp_path)
    _three_candidate_scans()
    _confirm(client, ["mbox:a:1"])
    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 200

    # Le compte rendu (avec ou sans identifiant) ne ressuscite rien.
    client.post(
        "/api/thunderbird/bridge/event",
        json={"event": "cleaner_move", "payload": {"request_id": "x", "moved_count": 1}},
    )
    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 400

    assert _confirm(client, ["mbox:a:2"]).status_code == 200
    payload = client.get("/api/thunderbird/cleaner/latest-request").json()
    assert [c["uid"] for c in payload["candidates"]] == ["mbox:a:2"]


def test_a_new_scan_cancels_the_confirmed_request(tmp_path, monkeypatch):
    client = _client(tmp_path)
    _three_candidate_scans()
    assert _confirm(client, ["mbox:a:1"]).status_code == 200

    class _NoThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(web_app.threading, "Thread", _NoThread)
    assert client.post("/cleaner/scan/start", data={"source": "duplicates"}).status_code == 200

    assert client.get("/api/thunderbird/cleaner/latest-request").status_code == 400
