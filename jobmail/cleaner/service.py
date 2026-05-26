from __future__ import annotations

import logging
import shutil
import subprocess
from glob import glob
from datetime import datetime, timedelta, timezone
from pathlib import Path

from imap_tools import AND, MailBox

from ..config import Settings
from ..db import connect
from ..mail.thunderbird import read_mbox
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


def scan_thunderbird_promotions(
    settings: Settings,
    *,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    skip_mails: int = 0,
) -> CleanerReport:
    min_age = _clean_min_age(min_age_days, settings.cleaner_min_age_days)
    limit = _clean_limit(max_mails, settings.cleaner_max_mails)
    paths = _resolve_mbox_paths(settings.cleaner_mbox_patterns)
    if not paths:
        raise CleanerError("Aucun fichier Thunderbird Inbox trouve pour le cleaner.")

    report = CleanerReport()
    skipped = 0
    for path in paths:
        mailbox_name = path.parent.name
        logger.info("Cleaner scanning mbox mailbox=%s path=%s", mailbox_name, path)
        for mail in read_mbox(path):
            if skipped < skip_mails:
                skipped += 1
                continue
            if report.scanned_count >= limit:
                logger.info(
                    "Cleaner MBOX scan stopped at max_mails=%d candidates=%d skip_mails=%d",
                    limit,
                    report.candidate_count,
                    skip_mails,
                )
                return report

            report.scanned_count += 1
            if not _is_older_than(mail.received_at, min_age):
                logger.info("Cleaner skipped mbox_offset=%s reason=too_recent", mail.mbox_offset)
                continue

            decision = classify_cleaner_candidate(mail.subject, mail.body_text, mail.sender)
            if decision.safety_hit:
                logger.info(
                    "Cleaner skipped mbox_offset=%s reason=safety_keyword:%s",
                    mail.mbox_offset,
                    decision.safety_hit,
                )
                continue
            if not decision.is_candidate:
                continue

            report.candidates.append(
                CleanerCandidate(
                    uid=f"mbox:{mailbox_name}:{mail.mbox_offset}",
                    received_at=mail.received_at,
                    sender=mail.sender,
                    subject=mail.subject,
                    reason=decision.reason,
                    source="mbox",
                    mailbox=mailbox_name,
                    source_path=str(path),
                )
            )

    logger.info(
        "Cleaner MBOX scan done scanned=%d candidates=%d min_age_days=%d max_mails=%d",
        report.scanned_count,
        report.candidate_count,
        min_age,
        limit,
    )
    return report


def scan_parsed_job_mails(
    settings: Settings,
    *,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    include_interesting: bool = False,
) -> CleanerReport:
    min_age = _clean_min_age(min_age_days, settings.cleaner_min_age_days)
    limit = _clean_limit(max_mails, settings.cleaner_max_mails)
    paths_by_mailbox = {path.parent.name: path for path in _resolve_mbox_paths(settings.cleaner_mbox_patterns)}

    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age)
    sql = """
        SELECT e.uid, e.subject, e.sender, e.received_at, o.id AS offer_id,
               o.title, o.company, o.status, o.relevance_score
        FROM emails e
        JOIN offers o ON o.email_uid = e.uid
        WHERE e.job_related = 1
        ORDER BY e.received_at ASC
    """
    report = CleanerReport()
    with connect(settings.db_path) as conn:
        rows = conn.execute(sql).fetchall()

    for row in rows:
        report.scanned_count += 1
        if report.candidate_count >= limit:
            break
        parsed_uid = _stored_email_uid_to_mbox_uid(row["uid"])
        if parsed_uid is None:
            continue
        mailbox, _offset = _split_mbox_uid(parsed_uid)
        received_at = datetime.fromisoformat(row["received_at"])
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        if received_at >= cutoff:
            continue
        status = row["status"] or ""
        score = int(row["relevance_score"] or 0)
        if status == "interesting" and not include_interesting:
            continue
        if status == "replied":
            continue
        if status != "ignored" and score > 3:
            continue

        title = row["title"] or row["subject"]
        reason = f"job deja parse; status={status}; score={score}/10"
        if row["company"]:
            reason += f"; company={row['company']}"
        report.candidates.append(
            CleanerCandidate(
                uid=parsed_uid,
                received_at=received_at,
                sender=row["sender"],
                subject=title,
                reason=reason,
                source="job",
                mailbox=mailbox,
                source_path=str(paths_by_mailbox.get(mailbox, "")),
                offer_id=int(row["offer_id"] or 0),
                status=status,
                score=score,
                company=row["company"] or "",
            )
        )

    logger.info(
        "Cleaner parsed jobs scan done scanned=%d candidates=%d include_interesting=%s",
        report.scanned_count,
        report.candidate_count,
        include_interesting,
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


def move_thunderbird_to_trash(
    settings: Settings,
    *,
    uids: list[str],
    min_age_days: int | None = None,
    max_mails: int | None = None,
    require_thunderbird_closed: bool = True,
) -> tuple[int, CleanerReport]:
    if not uids:
        raise CleanerError("Aucun mail selectionne.")
    if require_thunderbird_closed and _thunderbird_is_running():
        raise CleanerError("Ferme Thunderbird avant de deplacer des mails MBOX, puis relance l'action.")

    min_age = _clean_min_age(min_age_days, settings.cleaner_min_age_days)
    selected = _parse_mbox_uids(_dedupe_uids(uids))
    paths_by_mailbox = {path.parent.name: path for path in _resolve_mbox_paths(settings.cleaner_mbox_patterns)}

    moved_candidates: list[CleanerCandidate] = []
    moved_count = 0
    for mailbox, offsets in selected.items():
        path = paths_by_mailbox.get(mailbox)
        if path is None:
            raise CleanerError(f"MBOX introuvable pour le compte Thunderbird {mailbox!r}.")
        moved, candidates = _move_offsets_to_trash(path, mailbox, offsets, min_age)
        moved_count += moved
        moved_candidates.extend(candidates)

    if moved_count == 0:
        raise CleanerError("Aucun mail selectionne ne passe les regles de securite.")

    report = CleanerReport(scanned_count=len(uids), candidates=moved_candidates)
    logger.info("Cleaner Thunderbird moved count=%d", moved_count)
    return moved_count, report


def move_parsed_jobs_to_trash(
    settings: Settings,
    *,
    uids: list[str],
    min_age_days: int | None = None,
    max_mails: int | None = None,
    require_thunderbird_closed: bool = True,
) -> tuple[int, CleanerReport]:
    allowed = {
        candidate.uid: candidate
        for candidate in scan_parsed_job_mails(
            settings,
            min_age_days=min_age_days,
            max_mails=max_mails,
            include_interesting=False,
        ).candidates
    }
    safe_uids = [uid for uid in _dedupe_uids(uids) if uid in allowed]
    if not safe_uids:
        raise CleanerError("Aucun mail de job selectionne ne passe les regles de securite.")
    return _move_mbox_uids_to_trash(
        settings,
        uids=safe_uids,
        min_age_days=min_age_days,
        require_thunderbird_closed=require_thunderbird_closed,
        validator="parsed_job",
    )


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


def _resolve_mbox_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        for match in glob(pattern):
            path = Path(match)
            if path.is_file() and path.name == "Inbox":
                paths.append(path)
    return sorted(set(paths), key=lambda path: str(path).lower())


def _parse_mbox_uids(uids: list[str]) -> dict[str, set[int]]:
    selected: dict[str, set[int]] = {}
    for uid in uids:
        parts = uid.split(":")
        if len(parts) != 3 or parts[0] != "mbox":
            raise CleanerError("Selection Thunderbird invalide.")
        mailbox = parts[1]
        try:
            offset = int(parts[2])
        except ValueError as e:
            raise CleanerError("Selection Thunderbird invalide.") from e
        selected.setdefault(mailbox, set()).add(offset)
    return selected


def _move_mbox_uids_to_trash(
    settings: Settings,
    *,
    uids: list[str],
    min_age_days: int | None,
    require_thunderbird_closed: bool,
    validator: str,
) -> tuple[int, CleanerReport]:
    if not uids:
        raise CleanerError("Aucun mail selectionne.")
    if require_thunderbird_closed and _thunderbird_is_running():
        raise CleanerError("Ferme Thunderbird avant de deplacer des mails MBOX, puis relance l'action.")

    min_age = _clean_min_age(min_age_days, settings.cleaner_min_age_days)
    selected = _parse_mbox_uids(_dedupe_uids(uids))
    paths_by_mailbox = {path.parent.name: path for path in _resolve_mbox_paths(settings.cleaner_mbox_patterns)}

    moved_candidates: list[CleanerCandidate] = []
    moved_count = 0
    for mailbox, offsets in selected.items():
        path = paths_by_mailbox.get(mailbox)
        if path is None:
            raise CleanerError(f"MBOX introuvable pour le compte Thunderbird {mailbox!r}.")
        moved, candidates = _move_offsets_to_trash(path, mailbox, offsets, min_age, validator=validator)
        moved_count += moved
        moved_candidates.extend(candidates)

    if moved_count == 0:
        raise CleanerError("Aucun mail selectionne ne passe les regles de securite.")

    report = CleanerReport(scanned_count=len(uids), candidates=moved_candidates)
    logger.info("Cleaner Thunderbird moved count=%d validator=%s", moved_count, validator)
    return moved_count, report


def _move_offsets_to_trash(
    inbox_path: Path,
    mailbox: str,
    selected_offsets: set[int],
    min_age_days: int,
    *,
    validator: str = "promotion",
) -> tuple[int, list[CleanerCandidate]]:
    chunks = _read_mbox_chunks(inbox_path)
    selected_chunks: dict[int, bytes] = {}
    moved_candidates: list[CleanerCandidate] = []

    for offset, chunk in chunks:
        if offset not in selected_offsets:
            continue
        mail = next(read_mbox(inbox_path, start_offset=offset), None)
        if mail is None or mail.mbox_offset != offset:
            continue
        if not _is_older_than(mail.received_at, min_age_days):
            logger.info("Cleaner refused mbox_offset=%s reason=too_recent", offset)
            continue
        if validator == "promotion":
            decision = classify_cleaner_candidate(mail.subject, mail.body_text, mail.sender)
            if decision.safety_hit or not decision.is_candidate:
                logger.info("Cleaner refused mbox_offset=%s reason=safety_or_not_candidate", offset)
                continue
            reason = decision.reason
            source = "mbox"
        else:
            reason = "job deja parse dans SQLite"
            source = "job"
        selected_chunks[offset] = chunk
        moved_candidates.append(
            CleanerCandidate(
                uid=f"mbox:{mailbox}:{offset}",
                received_at=mail.received_at,
                sender=mail.sender,
                subject=mail.subject,
                reason=reason,
                source=source,
                mailbox=mailbox,
                source_path=str(inbox_path),
            )
        )

    if not selected_chunks:
        return 0, []

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = inbox_path.with_name(f"{inbox_path.name}.jobmail-backup-{timestamp}")
    shutil.copy2(inbox_path, backup_path)

    trash_path = inbox_path.with_name("Trash")
    with trash_path.open("ab") as trash:
        for offset in sorted(selected_chunks):
            chunk = selected_chunks[offset]
            if trash.tell() > 0 and not chunk.startswith(b"\n"):
                trash.write(b"\n")
            trash.write(chunk)
            if not chunk.endswith(b"\n"):
                trash.write(b"\n")

    with inbox_path.open("wb") as inbox:
        for offset, chunk in chunks:
            if offset not in selected_chunks:
                inbox.write(chunk)

    _remove_thunderbird_index(inbox_path)
    _remove_thunderbird_index(trash_path)
    logger.info(
        "Cleaner moved mbox mailbox=%s count=%d backup=%s trash=%s",
        mailbox,
        len(selected_chunks),
        backup_path,
        trash_path,
    )
    return len(selected_chunks), moved_candidates


def _read_mbox_chunks(path: Path) -> list[tuple[int, bytes]]:
    from ..mail.mbox_reader import iter_with_offsets

    raw = path.read_bytes()
    offsets = [offset for offset, _message in iter_with_offsets(path)]
    chunks: list[tuple[int, bytes]] = []
    for index, offset in enumerate(offsets):
        next_offset = offsets[index + 1] if index + 1 < len(offsets) else len(raw)
        chunks.append((offset, raw[offset:next_offset]))
    return chunks


def _remove_thunderbird_index(mbox_path: Path) -> None:
    msf = mbox_path.with_name(f"{mbox_path.name}.msf")
    if msf.exists():
        msf.unlink()


def _thunderbird_is_running() -> bool:
    powershell = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if not powershell.exists():
        return False
    try:
        proc = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-Command",
                "if (Get-Process thunderbird -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _stored_email_uid_to_mbox_uid(uid: str) -> str | None:
    if ":mbox-" not in uid:
        return None
    mailbox, offset_raw = uid.rsplit(":mbox-", 1)
    try:
        offset = int(offset_raw)
    except ValueError:
        return None
    return f"mbox:{mailbox}:{offset}"


def _split_mbox_uid(uid: str) -> tuple[str, int]:
    parsed = _parse_mbox_uids([uid])
    mailbox = next(iter(parsed))
    return mailbox, next(iter(parsed[mailbox]))
