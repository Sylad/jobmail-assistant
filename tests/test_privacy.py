from __future__ import annotations

from datetime import datetime

import pytest

from jobmail.extraction.base import CloudLLMProvider, PrivacyError
from jobmail.models import OfferExtraction, RawEmail
from jobmail.privacy import anonymize_email, anonymize_text


class RecordingCloudProvider(CloudLLMProvider):
    def __init__(self) -> None:
        self.sent: list[RawEmail] = []

    def _extract_job_related(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        self.sent.append(email)
        return OfferExtraction(title=email.subject)


def _email(subject: str, body: str, sender: str = "alice@example.com") -> RawEmail:
    return RawEmail(
        uid="p1",
        message_id="<p1@local>",
        subject=subject,
        sender=sender,
        received_at=datetime(2026, 5, 25),
        body_text=body,
    )


def test_anonymize_text_removes_direct_identifiers():
    text = "Contact alice@example.com, +33 6 12 34 56 78, https://example.com/private"

    redacted = anonymize_text(text)

    assert "alice@example.com" not in redacted
    assert "+33 6 12 34 56 78" not in redacted
    assert "https://example.com/private" not in redacted
    assert "[redacted-email]" in redacted
    assert "[redacted-phone]" in redacted
    assert "[redacted-url]" in redacted


def test_anonymize_email_clears_html_and_sender():
    email = _email("Mission Java", "Ecrire à bob@example.com", sender="bob@example.com")

    safe = anonymize_email(email)

    assert safe.sender == "[redacted-email]"
    assert "bob@example.com" not in safe.body_text
    assert safe.body_html == ""


def test_cloud_provider_refuses_non_job_email_before_network_step():
    provider = RecordingCloudProvider()
    email = _email("Commande", "Votre colis arrive demain.")

    with pytest.raises(PrivacyError):
        provider.extract(email, "Java GeoServer")

    assert provider.sent == []


def test_cloud_provider_anonymizes_job_email_before_network_step():
    provider = RecordingCloudProvider()
    email = _email(
        "Mission Java GeoServer",
        "Contact alice@example.com pour une mission Java GeoServer.",
        sender="alice@example.com",
    )

    provider.extract(email, "Java GeoServer")

    assert len(provider.sent) == 1
    assert provider.sent[0].sender == "[redacted-email]"
    assert "alice@example.com" not in provider.sent[0].body_text
