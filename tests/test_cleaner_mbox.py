from __future__ import annotations

from pathlib import Path

from jobmail.cleaner.service import scan_thunderbird_promotions
from jobmail.config import Settings


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
    assert report.candidates[0].can_move is False
    assert "Newsletter promo" == report.candidates[0].subject
