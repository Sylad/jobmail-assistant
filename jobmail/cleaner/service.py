from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from imap_tools import AND, MailBox

from ..config import Settings
from ..mail.parser import html_to_text, normalize_body
from .models import CleanerCandidate, CleanerReport
from .rules import classify_cleaner_candidate

logger = logging.getLogger(__name__)


class CleanerError(RuntimeError):
    pass


def scan_old_promotions(
    settings: Settings,
    *,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    uids: list[str] | None = None,
) -> CleanerReport:
    if not settings.imap_enabled:
        raise CleanerError("IMAP n'est pas configure. Le cleaner ne touche jamais aux MBOX Thunderbird.")

    min_age = _clean_min_age(min_age_days, settings.cleaner_min_age_days)
    limit = _clean_limit(max_mails, settings.cleaner_max_mails)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age)).date()

    report = CleanerReport()
    query = AND(uid=uids) if uids else AND(date_lt=cutoff)
    fetch_limit = None if uids else limit

    with MailBox(settings.imap_host, port=settings.imap_port).login(
        settings.imap_user,
        settings.imap_password,
        initial_folder=settings.imap_folder,
    ) as mailbox:
        for msg in mailbox.fetch(query, limit=fetch_limit, reverse=True, mark_seen=False):
            report.scanned_count += 1
            if uids and not _is_older_than(msg.date, min_age):
                logger.info("Cleaner skipped uid=%s reason=too_recent", msg.uid)
                continue

            body_text = _message_text(msg)
            decision = classify_cleaner_candidate(msg.subject or "", body_text, msg.from_ or "")
            if decision.safety_hit:
                logger.info("Cleaner skipped uid=%s reason=safety_keyword:%s", msg.uid, decision.safety_hit)
                continue
            if not decision.is_candidate:
                continue

            report.candidates.append(
                CleanerCandidate(
                    uid=str(msg.uid),
                    received_at=msg.date,
                    sender=msg.from_ or "",
                    subject=msg.subject or "",
                    reason=decision.reason,
                )
            )

    logger.info(
        "Cleaner scan done scanned=%d candidates=%d min_age_days=%d max_mails=%d",
        report.scanned_count,
        report.candidate_count,
        min_age,
        limit,
    )
    return report


def move_to_delete(
    settings: Settings,
    *,
    uids: list[str],
    min_age_days: int | None = None,
    max_mails: int | None = None,
) -> tuple[int, CleanerReport]:
    if not uids:
        raise CleanerError("Aucun mail selectionne.")

    # Re-run rules on selected UIDs before moving. This keeps the action safe
    # even if a stale or forged form posts arbitrary message ids.
    report = scan_old_promotions(
        settings,
        min_age_days=min_age_days,
        max_mails=max_mails,
        uids=_dedupe_uids(uids),
    )
    safe_uids = [candidate.uid for candidate in report.candidates]
    if not safe_uids:
        raise CleanerError("Aucun mail selectionne ne passe les regles de securite.")

    target = settings.cleaner_delete_folder
    with MailBox(settings.imap_host, port=settings.imap_port).login(
        settings.imap_user,
        settings.imap_password,
        initial_folder=settings.imap_folder,
    ) as mailbox:
        if not mailbox.folder.exists(target):
            try:
                mailbox.folder.create(target)
            except Exception as exc:  # pragma: no cover - depends on IMAP server
                raise CleanerError(f"Impossible de creer le dossier IMAP {target!r}: {exc}") from exc
        mailbox.move(safe_uids, target)

    logger.info("Cleaner moved count=%d destination=%s", len(safe_uids), target)
    return len(safe_uids), report


def _message_text(msg) -> str:
    body_text = (getattr(msg, "text", "") or "").strip()
    body_html = getattr(msg, "html", "") or ""
    if not body_text and body_html:
        body_text = html_to_text(body_html)
    return normalize_body(body_text)


def _is_older_than(received_at: datetime, min_age_days: int) -> bool:
    ref = received_at
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return ref < datetime.now(timezone.utc) - timedelta(days=min_age_days)


def _clean_min_age(value: int | None, default: int) -> int:
    return max(1, int(value if value is not None else default))


def _clean_limit(value: int | None, default: int) -> int:
    return max(1, min(1000, int(value if value is not None else default)))


def _dedupe_uids(uids: list[str]) -> list[str]:
    return list(dict.fromkeys(uid for uid in uids if uid.strip()))
