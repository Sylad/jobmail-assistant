from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path

from imap_tools import AND, MailBox

from ..config import Settings
from ..db import connect
from ..mail.mbox_reader import _FROM_LINE, _is_envelope
from ..mail.parser import html_to_text, normalize_body
from ..mail.thunderbird import read_mbox
from .models import CleanerCandidate, CleanerReport
from .rules import classify_cleaner_candidate

logger = logging.getLogger(__name__)


class CleanerError(RuntimeError):
    pass


@dataclass
class CleanerBackupFile:
    path: Path
    size_bytes: int
    modified_at: datetime
    age_days: int
    eligible: bool


@dataclass
class CleanerBackupSummary:
    retention_days: int
    backup_roots: list[Path] = field(default_factory=list)
    files: list[CleanerBackupFile] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files)

    @property
    def eligible_count(self) -> int:
        return sum(1 for file in self.files if file.eligible)

    @property
    def eligible_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files if file.eligible)


@dataclass
class CleanerBackupCleanup:
    deleted_count: int
    deleted_bytes: int
    summary: CleanerBackupSummary


@dataclass
class CleanerTempFile:
    path: Path
    size_bytes: int
    modified_at: datetime


@dataclass
class CleanerTempSummary:
    files: list[CleanerTempFile] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files)


@dataclass
class CleanerTempCleanup:
    moved_count: int
    moved_bytes: int
    destination: Path
    summary: CleanerTempSummary


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


def scan_thunderbird_regex(
    settings: Settings,
    *,
    sender_regex: str = "",
    subject_regex: str = "",
    regex_rules: list[tuple[str, str]] | None = None,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    progress_callback: Callable[[CleanerReport, str], None] | None = None,
) -> CleanerReport:
    rules = _compile_cleaner_regex_rules(sender_regex, subject_regex, regex_rules)
    min_age = _clean_min_age(min_age_days, settings.cleaner_min_age_days)
    limit = _clean_unbounded_limit(max_mails)
    paths = _resolve_mbox_paths(settings.cleaner_mbox_patterns)
    if not paths:
        raise CleanerError("Aucun fichier Thunderbird Inbox trouve avec CLEANER_MBOX_GLOBS.")

    report = CleanerReport()
    for path in paths:
        mailbox_name = path.parent.name
        logger.info("Cleaner regex scanning mbox mailbox=%s path=%s", mailbox_name, path)
        if progress_callback:
            progress_callback(report, mailbox_name)
        for mail in read_mbox(path):
            if limit and report.scanned_count >= limit:
                logger.info("Cleaner regex MBOX scan stopped at max_mails=%d candidates=%d", limit, report.candidate_count)
                if progress_callback:
                    progress_callback(report, mailbox_name)
                return report
            report.scanned_count += 1
            if progress_callback and report.scanned_count % 250 == 0:
                progress_callback(report, mailbox_name)
            if not _is_older_than(mail.received_at, min_age):
                continue
            regex_reason = _regex_match_reason(mail.sender, mail.subject, rules)
            if not regex_reason:
                continue
            decision = classify_cleaner_candidate(mail.subject, mail.body_text, mail.sender)
            if decision.safety_hit:
                logger.info("Cleaner regex skipped mbox_offset=%s reason=safety_keyword:%s", mail.mbox_offset, decision.safety_hit)
                continue
            report.candidates.append(
                CleanerCandidate(
                    uid=f"mbox:{mailbox_name}:{mail.mbox_offset}",
                    received_at=mail.received_at,
                    sender=mail.sender,
                    subject=mail.subject,
                    reason=regex_reason,
                    source="mbox",
                    mailbox=mailbox_name,
                    source_path=str(path),
                )
            )
    if progress_callback:
        progress_callback(report, "")
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


def move_thunderbird_regex_to_trash(
    settings: Settings,
    *,
    sender_regex: str = "",
    subject_regex: str = "",
    regex_rules: list[tuple[str, str]] | None = None,
    min_age_days: int | None = None,
    max_mails: int | None = None,
    require_thunderbird_closed: bool = True,
) -> tuple[int, CleanerReport]:
    report = scan_thunderbird_regex(
        settings,
        sender_regex=sender_regex,
        subject_regex=subject_regex,
        regex_rules=regex_rules,
        min_age_days=min_age_days,
        max_mails=max_mails,
    )
    if not report.candidates:
        raise CleanerError("Aucun mail ne correspond aux regex apres application des regles de securite.")
    moved_count, moved_report = _move_mbox_uids_to_trash(
        settings,
        uids=[candidate.uid for candidate in report.candidates],
        min_age_days=min_age_days,
        require_thunderbird_closed=require_thunderbird_closed,
        validator="regex",
    )
    moved_report.scanned_count = report.scanned_count
    return moved_count, moved_report


def move_scanned_regex_uids_to_trash(
    settings: Settings,
    *,
    uids: list[str],
    min_age_days: int | None = None,
    require_thunderbird_closed: bool = True,
) -> tuple[int, CleanerReport]:
    return _move_mbox_uids_to_trash(
        settings,
        uids=uids,
        min_age_days=min_age_days,
        require_thunderbird_closed=require_thunderbird_closed,
        validator="regex",
    )


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


def list_cleaner_backups(settings: Settings, *, retention_days: int | None = None) -> CleanerBackupSummary:
    retention = _clean_backup_retention(retention_days, settings.cleaner_backup_retention_days)
    roots = _cleaner_backup_roots(settings)
    now = datetime.now(timezone.utc)
    files: list[CleanerBackupFile] = []

    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jobmail-backup-*.mbox"), key=lambda item: str(item).lower()):
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            age_days = max(0, int((now - modified_at).total_seconds() // 86400))
            files.append(
                CleanerBackupFile(
                    path=path,
                    size_bytes=stat.st_size,
                    modified_at=modified_at,
                    age_days=age_days,
                    eligible=modified_at < now - timedelta(days=retention),
                )
            )

    return CleanerBackupSummary(retention_days=retention, backup_roots=roots, files=files)


def delete_old_cleaner_backups(settings: Settings, *, retention_days: int | None = None) -> CleanerBackupCleanup:
    summary = list_cleaner_backups(settings, retention_days=retention_days)
    deleted_count = 0
    deleted_bytes = 0
    for backup in summary.files:
        if not backup.eligible:
            continue
        try:
            backup.path.unlink()
        except FileNotFoundError:
            continue
        deleted_count += 1
        deleted_bytes += backup.size_bytes
        logger.info("Cleaner deleted old backup=%s size=%d", backup.path, backup.size_bytes)
    refreshed = list_cleaner_backups(settings, retention_days=summary.retention_days)
    return CleanerBackupCleanup(
        deleted_count=deleted_count,
        deleted_bytes=deleted_bytes,
        summary=refreshed,
    )


def list_orphan_cleaner_temp_files(settings: Settings) -> CleanerTempSummary:
    files: list[CleanerTempFile] = []
    for inbox_path in _resolve_mbox_paths(settings.cleaner_mbox_patterns):
        for path in sorted(inbox_path.parent.glob(f".{inbox_path.name}.jobmail-tmp-*")):
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            files.append(
                CleanerTempFile(
                    path=path,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                )
            )
    return CleanerTempSummary(files=files)


def move_orphan_cleaner_temp_files(settings: Settings, *, destination_root: Path | None = None) -> CleanerTempCleanup:
    if _thunderbird_is_running():
        raise CleanerError("Thunderbird doit etre ferme avant de deplacer les temporaires orphelins.")
    summary = list_orphan_cleaner_temp_files(settings)
    if destination_root is None:
        destination_root = Path.home() / "jobmail-orphan-temp"
    destination = destination_root / datetime.now().strftime("orphan-tmp-%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=True)

    moved_count = 0
    moved_bytes = 0
    for temp_file in summary.files:
        target = destination / f"{temp_file.path.parent.name}-{temp_file.path.name}"
        shutil.move(str(temp_file.path), str(target))
        moved_count += 1
        moved_bytes += temp_file.size_bytes
        logger.info("Cleaner moved orphan temp=%s target=%s size=%d", temp_file.path, target, temp_file.size_bytes)

    refreshed = list_orphan_cleaner_temp_files(settings)
    return CleanerTempCleanup(
        moved_count=moved_count,
        moved_bytes=moved_bytes,
        destination=destination,
        summary=refreshed,
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


def _clean_unbounded_limit(value: int | None) -> int:
    if value is None:
        return 0
    return max(0, int(value))


def _clean_backup_retention(value: int | None, default: int) -> int:
    return max(1, min(3650, int(value if value is not None else default)))


CompiledRegexRule = tuple[int, re.Pattern | None, re.Pattern | None]


def _compile_cleaner_regex_rules(
    sender_regex: str,
    subject_regex: str,
    regex_rules: list[tuple[str, str]] | None,
) -> list[CompiledRegexRule]:
    raw_rules = [(sender_regex, subject_regex)]
    if regex_rules is not None:
        raw_rules = regex_rules

    compiled: list[CompiledRegexRule] = []
    errors: list[str] = []
    for index, (sender_raw, subject_raw) in enumerate(raw_rules, start=1):
        sender_raw = sender_raw.strip()
        subject_raw = subject_raw.strip()
        if not sender_raw and not subject_raw:
            continue
        try:
            sender_pattern = re.compile(sender_raw, re.IGNORECASE) if sender_raw else None
            subject_pattern = re.compile(subject_raw, re.IGNORECASE) if subject_raw else None
        except re.error as e:
            errors.append(f"regle {index}: {e}")
            continue
        compiled.append((index, sender_pattern, subject_pattern))

    if errors:
        raise CleanerError("Regex invalide: " + "; ".join(errors))
    if not compiled:
        raise CleanerError("Indique au moins une regle avec une regex expediteur ou objet.")
    return compiled


def _single_regex_match_reason(
    sender: str,
    subject: str,
    sender_pattern: re.Pattern | None,
    subject_pattern: re.Pattern | None,
) -> str:
    hits: list[str] = []
    if sender_pattern:
        if not sender_pattern.search(sender):
            return ""
        hits.append(f"regex expediteur: {sender_pattern.pattern}")
    if subject_pattern:
        if not subject_pattern.search(subject):
            return ""
        hits.append(f"regex objet: {subject_pattern.pattern}")
    return ", ".join(hits)


def _regex_match_reason(
    sender: str,
    subject: str,
    rules: list[CompiledRegexRule] | re.Pattern | None,
    subject_pattern: re.Pattern | None = None,
) -> str:
    if not isinstance(rules, list):
        return _single_regex_match_reason(sender, subject, rules, subject_pattern)

    for index, sender_pattern, rule_subject_pattern in rules:
        reason = _single_regex_match_reason(sender, subject, sender_pattern, rule_subject_pattern)
        if reason:
            return f"regle {index}: {reason}"
    return ""


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
    candidate_by_offset: dict[int, CleanerCandidate] = {}

    for offset in sorted(selected_offsets):
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
        elif validator == "regex":
            decision = classify_cleaner_candidate(mail.subject, mail.body_text, mail.sender)
            if decision.safety_hit:
                logger.info("Cleaner refused mbox_offset=%s reason=safety_keyword:%s", offset, decision.safety_hit)
                continue
            reason = "regex validee apres dry-run"
            source = "mbox"
        else:
            reason = "job deja parse dans SQLite"
            source = "job"
        candidate_by_offset[offset] = (
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

    if not candidate_by_offset:
        return 0, []

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = _create_mbox_backup(inbox_path, timestamp)
    temp_path = inbox_path.with_name(f".{inbox_path.name}.jobmail-tmp-{timestamp}")
    trash_path = inbox_path.with_name("Trash")
    moved_offsets: set[int] = set()

    try:
        with temp_path.open("wb") as inbox, trash_path.open("ab") as trash:
            for offset, chunk in _iter_mbox_chunks(inbox_path):
                if offset in candidate_by_offset:
                    if trash.tell() > 0 and not chunk.startswith(b"\n"):
                        trash.write(b"\n")
                    trash.write(chunk)
                    if not chunk.endswith(b"\n"):
                        trash.write(b"\n")
                    moved_offsets.add(offset)
                else:
                    inbox.write(chunk)
        shutil.copystat(inbox_path, temp_path)
        os.replace(temp_path, inbox_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    moved_candidates = [candidate_by_offset[offset] for offset in sorted(moved_offsets)]

    _remove_thunderbird_index(inbox_path)
    _remove_thunderbird_index(trash_path)
    logger.info(
        "Cleaner moved mbox mailbox=%s count=%d backup=%s trash=%s",
        mailbox,
        len(moved_offsets),
        backup_path,
        trash_path,
    )
    return len(moved_offsets), moved_candidates


def _create_mbox_backup(inbox_path: Path, timestamp: str) -> Path:
    backup_dir = _backup_dir_for_inbox(inbox_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{inbox_path.name}.jobmail-backup-{timestamp}.mbox"
    try:
        os.link(inbox_path, backup_path)
        logger.info("Cleaner created mbox hardlink backup=%s", backup_path)
    except OSError:
        shutil.copy2(inbox_path, backup_path)
        logger.info("Cleaner created mbox copied backup=%s", backup_path)
    return backup_path


def _backup_dir_for_inbox(inbox_path: Path) -> Path:
    parts = inbox_path.parts
    if "Mail" in parts:
        mail_index = parts.index("Mail")
        profile_root = Path(*parts[:mail_index])
        account_name = inbox_path.parent.name
        return profile_root / "jobmail-backups" / "Mail" / account_name
    return inbox_path.parent / "jobmail-backups"


def _cleaner_backup_roots(settings: Settings) -> list[Path]:
    roots = {_backup_dir_for_inbox(path) for path in _resolve_mbox_paths(settings.cleaner_mbox_patterns)}
    return sorted(roots, key=lambda path: str(path).lower())


def _iter_mbox_chunks(path: Path):
    with path.open("rb") as fh:
        msg_offset = fh.tell()
        msg_buf: list[bytes] = []
        first = True

        while True:
            pos_before = fh.tell()
            line = fh.readline()
            if not line:
                break
            if not first and _FROM_LINE.match(line) and _is_envelope(fh, line):
                yield msg_offset, b"".join(msg_buf)
                msg_offset = pos_before
                msg_buf = [line]
            else:
                msg_buf.append(line)
                first = False

        if msg_buf:
            yield msg_offset, b"".join(msg_buf)


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
