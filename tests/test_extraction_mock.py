from datetime import datetime

from jobmail.extraction.mock import MockExtractor
from jobmail.models import ContractType, RawEmail, WorkMode


def _email(subject: str, body: str, sender="hr@geocompany.fr") -> RawEmail:
    return RawEmail(
        uid="t1", message_id="<t1@local>", subject=subject,
        sender=sender, received_at=datetime(2026, 5, 25), body_text=body,
    )


def test_mock_extracts_technos_and_work_mode():
    e = _email(
        "Java Senior GeoServer / OpenLayers mission",
        "Stack: Java, Spring, Kubernetes, Docker, PostGIS. Hybride Paris.",
    )
    profile = "Java GeoServer OpenLayers Kubernetes"
    out = MockExtractor().extract(e, profile)
    assert "java" in [t.lower() for t in out.technos]
    assert "geoserver" in [t.lower() for t in out.technos]
    assert out.work_mode == WorkMode.HYBRID
    assert out.relevance_score >= 6


def test_mock_detects_freelance_and_tjm():
    e = _email("Mission freelance", "TJM 650, 6 mois renouvelable. Java.")
    out = MockExtractor().extract(e, "Java")
    assert out.contract_type == ContractType.FREELANCE


def test_mock_guesses_company_from_email_domain():
    e = _email("Poste Java", "Stack Java Spring", sender="recruiter@bigcorp.com")
    out = MockExtractor().extract(e, "Java")
    assert out.company == "Bigcorp"


def test_mock_zero_score_on_unrelated():
    e = _email("Random", "Hello world")
    out = MockExtractor().extract(e, "Java GeoServer")
    assert out.relevance_score == 0
