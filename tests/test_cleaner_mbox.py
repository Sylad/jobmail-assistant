from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jobmail.cleaner.service import (
    move_parsed_jobs_to_trash,
    move_thunderbird_regex_to_trash,
    move_thunderbird_to_trash,
    scan_parsed_job_mails,
    scan_thunderbird_regex,
    scan_thunderbird_promotions,
)
from jobmail.config import Settings
from jobmail.db import connect, init_db, insert_email, update_status, upsert_offer
from jobmail.models import OfferExtraction, OfferStatus, RawEmail


def _make_msg(idx: int, subject: str, body: str) -> str:
    return (
        f"From sender{idx}@example.com Mon Jan 05 12:00:00 2020\n"
        f"Date: Mon, 05 Jan 2020 12:00:00 +0000\n"
        f"From: newsletter{idx}@shop.example\n"
        f"To: me@example.com\n"
        f"Subject: {subject}\n"
        f"Message-Id: <clean-{idx}@local>\n"
        f"Content-Type: text/plain; charset=utf-8\n"
        f"\n"
        f"{body}\n"
        f"\n"
    )


def test_scan_thunderbird_promotions_reads_mbox_without_imap(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Newsletter promo", "Soldes et unsubscribe.")
        + _make_msg(2, "Newsletter facture", "Promotion avec facture importante."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        imap_host="",
        cleaner_mbox_globs=str(mbox),
        cleaner_max_mails=20,
    )

    report = scan_thunderbird_promotions(settings, min_age_days=7, max_mails=20)

    assert report.scanned_count == 2
    assert report.candidate_count == 1
    assert report.candidates[0].source == "mbox"
    assert report.candidates[0].can_move is True
    assert "Newsletter promo" == report.candidates[0].subject


def test_scan_thunderbird_promotions_can_skip_already_seen_window(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Newsletter first", "Soldes et unsubscribe.")
        + _make_msg(2, "Newsletter second", "Soldes et unsubscribe."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
        cleaner_max_mails=20,
    )

    report = scan_thunderbird_promotions(settings, min_age_days=7, max_mails=20, skip_mails=1)

    assert report.scanned_count == 1
    assert report.candidate_count == 1
    assert report.candidates[0].subject == "Newsletter second"


def test_move_thunderbird_to_trash_moves_selected_candidate(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Newsletter promo", "Soldes et unsubscribe.")
        + _make_msg(2, "Mission Java", "Votre candidature emploi Java."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
        cleaner_max_mails=20,
    )
    report = scan_thunderbird_promotions(settings, min_age_days=7, max_mails=20)

    moved_count, moved_report = move_thunderbird_to_trash(
        settings,
        uids=[report.candidates[0].uid],
        min_age_days=7,
        max_mails=20,
        require_thunderbird_closed=False,
    )

    assert moved_count == 1
    assert moved_report.candidate_count == 1
    assert "Newsletter promo" not in mbox.read_text(encoding="utf-8")
    assert "Mission Java" in mbox.read_text(encoding="utf-8")
    assert "Newsletter promo" in (tmp_path / "Trash").read_text(encoding="utf-8")
    backups = list(tmp_path.glob("Inbox.jobmail-backup-*"))
    assert backups
    assert "Newsletter promo" in backups[0].read_text(encoding="utf-8")


def test_scan_thunderbird_regex_matches_sender_or_subject_and_keeps_safety(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Amazon recommande un casque", "Soldes et unsubscribe.")
        + _make_msg(2, "Amazon facture disponible", "Facture importante.")
        + _make_msg(3, "Mission Java", "Votre candidature emploi Java."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
    )

    report = scan_thunderbird_regex(settings, sender_regex="newsletter1", subject_regex="recommande", min_age_days=7)

    assert report.scanned_count == 3
    assert report.candidate_count == 1
    assert report.candidates[0].subject == "Amazon recommande un casque"
    assert "regex expediteur" in report.candidates[0].reason
    assert "regex objet" in report.candidates[0].reason


def test_scan_thunderbird_regex_requires_all_filled_fields_in_rule(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Amazon recommande un casque", "Soldes et unsubscribe.")
        + _make_msg(2, "Google Play recommande un jeu", "Newsletter sans sujet sensible."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
    )

    report = scan_thunderbird_regex(
        settings,
        regex_rules=[
            ("newsletter1", "Google Play"),
        ],
        min_age_days=7,
    )

    assert report.scanned_count == 2
    assert report.candidate_count == 0


def test_scan_thunderbird_regex_combines_multiple_rules(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Amazon recommande un casque", "Soldes et unsubscribe.")
        + _make_msg(2, "Google Play promo", "Newsletter sans sujet sensible.")
        + _make_msg(3, "Mission Java", "Votre candidature emploi Java."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
    )

    report = scan_thunderbird_regex(
        settings,
        regex_rules=[
            ("newsletter1", ""),
            ("", "Google Play"),
        ],
        min_age_days=7,
    )

    assert report.candidate_count == 2
    assert {candidate.subject for candidate in report.candidates} == {
        "Amazon recommande un casque",
        "Google Play promo",
    }
    assert {candidate.reason.split(":", 1)[0] for candidate in report.candidates} == {"regle 1", "regle 2"}


def test_move_thunderbird_regex_to_trash_moves_all_matches_in_one_action(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(
        _make_msg(1, "Amazon recommande un casque", "Soldes et unsubscribe.")
        + _make_msg(2, "Google Play promo", "Newsletter sans sujet sensible.")
        + _make_msg(3, "Mission Java", "Votre candidature emploi Java."),
        encoding="utf-8",
    )
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
    )

    moved_count, report = move_thunderbird_regex_to_trash(
        settings,
        regex_rules=[
            ("newsletter1", "recommande"),
            ("newsletter2", "promo"),
        ],
        min_age_days=7,
        require_thunderbird_closed=False,
    )

    assert moved_count == 2
    assert report.candidate_count == 2
    assert "Amazon recommande" not in mbox.read_text(encoding="utf-8")
    assert "Google Play promo" not in mbox.read_text(encoding="utf-8")
    assert "Mission Java" in mbox.read_text(encoding="utf-8")
    trash = (tmp_path / "Trash").read_text(encoding="utf-8")
    assert "Amazon recommande" in trash
    assert "Google Play promo" in trash


def test_scan_parsed_job_mails_only_keeps_ignored_or_low_score(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(_make_msg(1, "Mission Java", "Votre candidature emploi Java."), encoding="utf-8")
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
    )
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        ignored = RawEmail(
            uid=f"{tmp_path.name}:mbox-0",
            message_id="<job-1@local>",
            subject="Mission Java",
            sender="recruiter@example.com",
            received_at=datetime(2020, 1, 5, 12, 0, 0),
            body_text="Mission Java",
        )
        insert_email(conn, ignored, job_related=True, matched_keywords=["java"])
        offer_id = upsert_offer(conn, ignored.uid, OfferExtraction(title="Mission Java", relevance_score=8))
        update_status(conn, offer_id, OfferStatus.IGNORED)
        interesting = RawEmail(
            uid=f"{tmp_path.name}:mbox-999",
            message_id="<job-2@local>",
            subject="Mission GeoServer",
            sender="recruiter@example.com",
            received_at=datetime(2020, 1, 5, 12, 0, 0),
            body_text="Mission GeoServer",
        )
        insert_email(conn, interesting, job_related=True, matched_keywords=["geoserver"])
        interesting_id = upsert_offer(
            conn,
            interesting.uid,
            OfferExtraction(title="Mission GeoServer", relevance_score=9),
        )
        update_status(conn, interesting_id, OfferStatus.INTERESTING)
        replied = RawEmail(
            uid=f"{tmp_path.name}:mbox-500",
            message_id="<job-3@local>",
            subject="Mission PostGIS",
            sender="recruiter@example.com",
            received_at=datetime(2020, 1, 5, 12, 0, 0),
            body_text="Mission PostGIS",
        )
        insert_email(conn, replied, job_related=True, matched_keywords=["postgis"])
        replied_id = upsert_offer(conn, replied.uid, OfferExtraction(title="Mission PostGIS", relevance_score=8))
        update_status(conn, replied_id, OfferStatus.REPLIED)
        low_score = RawEmail(
            uid=f"{tmp_path.name}:mbox-700",
            message_id="<job-4@local>",
            subject="Alerte job board",
            sender="jobs@example.com",
            received_at=datetime(2020, 1, 5, 12, 0, 0),
            body_text="Alerte job board",
        )
        insert_email(conn, low_score, job_related=True, matched_keywords=["java"])
        upsert_offer(conn, low_score.uid, OfferExtraction(title="Alerte job board", relevance_score=3))

    report = scan_parsed_job_mails(settings, min_age_days=7, max_mails=20)

    assert report.candidate_count == 2
    assert report.candidates[0].source == "job"
    assert report.candidates[0].can_move is True
    assert report.candidates[0].uid.startswith("mbox:")
    assert "status=ignored" in report.candidates[0].reason
    assert report.candidates[0].offer_id > 0
    assert report.candidates[0].status == "ignored"
    assert report.candidates[0].score == 8
    assert {candidate.subject for candidate in report.candidates} == {"Mission Java", "Alerte job board"}


def test_move_parsed_jobs_to_trash_uses_db_allowlist(tmp_path: Path):
    mbox = tmp_path / "Inbox"
    mbox.write_text(_make_msg(1, "Mission Java", "Votre candidature emploi Java."), encoding="utf-8")
    settings = Settings(
        db_path=tmp_path / "test.db",
        cleaner_mbox_globs=str(mbox),
    )
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        email = RawEmail(
            uid=f"{tmp_path.name}:mbox-0",
            message_id="<job-1@local>",
            subject="Mission Java",
            sender="recruiter@example.com",
            received_at=datetime(2020, 1, 5, 12, 0, 0),
            body_text="Mission Java",
        )
        insert_email(conn, email, job_related=True, matched_keywords=["java"])
        offer_id = upsert_offer(conn, email.uid, OfferExtraction(title="Mission Java", relevance_score=8))
        update_status(conn, offer_id, OfferStatus.IGNORED)
    report = scan_parsed_job_mails(settings, min_age_days=7, max_mails=20)

    moved_count, _moved_report = move_parsed_jobs_to_trash(
        settings,
        uids=[report.candidates[0].uid],
        min_age_days=7,
        max_mails=20,
        require_thunderbird_closed=False,
    )

    assert moved_count == 1
    assert "Mission Java" not in mbox.read_text(encoding="utf-8")
    assert "Mission Java" in (tmp_path / "Trash").read_text(encoding="utf-8")
