"""Critical privacy test: non-job emails MUST NEVER reach the extractor."""
from __future__ import annotations

from datetime import datetime

from jobmail.db import connect, init_db
from jobmail.extraction.base import ExtractorProvider
from jobmail.models import OfferExtraction, RawEmail
from jobmail.pipeline import run as run_pipeline


class SpyExtractor(ExtractorProvider):
    def __init__(self) -> None:
        self.calls: list[RawEmail] = []

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        self.calls.append(email)
        return OfferExtraction(
            title=email.subject,
            company="SpyCo",
            relevance_score=5,
        )


def _email(uid: str, subject: str, body: str) -> RawEmail:
    return RawEmail(
        uid=uid,
        message_id=f"<{uid}@local>",
        subject=subject,
        sender="someone@example.com",
        received_at=datetime(2026, 5, 25, 12, 0, 0),
        body_text=body,
    )


def test_pipeline_does_not_send_non_job_to_extractor(tmp_settings, monkeypatch):
    spy = SpyExtractor()
    monkeypatch.setattr("jobmail.pipeline.get_extractor", lambda s: spy)

    emails = [
        _email("1", "Confirmation commande", "Votre colis arrive demain."),
        _email("2", "Newsletter Le Monde", "Articles du jour."),
        _email("3", "Mission freelance Java GeoServer", "Mission longue Paris."),
    ]
    stats = run_pipeline(source=iter(emails), settings=tmp_settings)

    assert len(spy.calls) == 1
    assert spy.calls[0].uid == "3"
    assert stats.sent_to_llm == 1
    assert stats.skipped_non_job == 2


def test_pipeline_dedup_does_not_resend_known_email(tmp_settings, monkeypatch):
    spy = SpyExtractor()
    monkeypatch.setattr("jobmail.pipeline.get_extractor", lambda s: spy)

    email = _email("42", "Opportunité Java Spring", "Mission Paris.")
    run_pipeline(source=iter([email]), settings=tmp_settings)
    run_pipeline(source=iter([email]), settings=tmp_settings)

    assert len(spy.calls) == 1, "Extractor was called twice for the same UID"


def test_pipeline_stores_classification_for_skipped_mails(tmp_settings, monkeypatch):
    spy = SpyExtractor()
    monkeypatch.setattr("jobmail.pipeline.get_extractor", lambda s: spy)

    email = _email("skip-1", "Pub Carrefour", "Promo lessive.")
    run_pipeline(source=iter([email]), settings=tmp_settings)

    init_db(tmp_settings.db_path)
    with connect(tmp_settings.db_path) as conn:
        row = conn.execute("SELECT job_related FROM emails WHERE uid = ?", ("skip-1",)).fetchone()
    assert row is not None
    assert row["job_related"] == 0


def test_dry_run_never_instantiates_extractor(tmp_settings, monkeypatch):
    def fail_get_extractor(settings):
        raise AssertionError("dry-run must not create any LLM provider")

    monkeypatch.setattr("jobmail.pipeline.get_extractor", fail_get_extractor)

    emails = [
        _email("dry-1", "Mission Java GeoServer", "Mission longue Java GeoServer."),
        _email("dry-2", "Newsletter", "Articles du jour."),
    ]
    stats = run_pipeline(source=iter(emails), settings=tmp_settings, dry_run=True)

    assert stats.dry_run is True
    assert stats.job_related == 1
    assert stats.sent_to_llm == 0
    assert stats.extracted == 0
