from __future__ import annotations

from datetime import datetime

from jobmail.db import connect, get_offer, init_db, insert_email, list_offers, upsert_offer
from jobmail.models import ContractType, OfferExtraction, OfferStatus, RawEmail, WorkMode


def test_sqlite_saves_email_classification_and_offer(tmp_path):
    db_path = tmp_path / "jobmail.db"
    init_db(db_path)
    email = RawEmail(
        uid="db-1",
        message_id="<db-1@local>",
        subject="Mission Java GeoServer",
        sender="recruiter@example.com",
        received_at=datetime(2026, 5, 25, 9, 30),
        body_text="Mission Java GeoServer PostGIS.",
        body_html='<a href="https://jobs.example.com/42">Voir</a>',
    )
    extraction = OfferExtraction(
        title="Senior Java GIS",
        company="Example",
        recruiter="Recruiter",
        location="Toulouse",
        work_mode=WorkMode.HYBRID,
        technos=["java", "geoserver", "postgis"],
        english_required=False,
        contract_type=ContractType.CDI,
        summary="Mission GIS Java.",
        relevance_score=9,
    )

    with connect(db_path) as conn:
        insert_email(conn, email, job_related=True, matched_keywords=["mission", "java"])
        offer_id = upsert_offer(conn, email.uid, extraction)
        row = conn.execute(
            "SELECT job_related, matched_keywords FROM emails WHERE uid = ?", (email.uid,)
        ).fetchone()

    with connect(db_path) as conn:
        offers = list_offers(conn, status=OfferStatus.NEW, min_score=8)
        detail = get_offer(conn, offer_id, with_body=True)

    assert offer_id > 0
    assert row["job_related"] == 1
    assert "java" in row["matched_keywords"]
    assert len(offers) == 1
    assert offers[0].extraction is not None
    assert offers[0].extraction.technos == ["java", "geoserver", "postgis"]
    assert detail is not None
    assert detail.body_html == '<a href="https://jobs.example.com/42">Voir</a>'
