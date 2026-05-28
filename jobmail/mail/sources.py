from __future__ import annotations

import glob
import logging
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import Settings, get_settings
from ..db import connect, get_mbox_state, init_db
from ..models import RawEmail
from .thunderbird import read_mbox


logger = logging.getLogger(__name__)


def resolve_mbox_paths(patterns: Iterable[str]) -> list[str]:
    """Expand configured Thunderbird MBOX globs into stable absolute paths."""
    paths: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        expanded = [p for p in sorted(glob.glob(pattern)) if Path(p).is_file()]
        if not expanded and Path(pattern).is_file():
            expanded = [pattern]
        for raw_path in expanded:
            path = str(Path(raw_path).expanduser().resolve())
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def build_mbox_source(
    paths: list[str],
    since_days: int | None = None,
    *,
    settings: Settings | None = None,
) -> Iterator[RawEmail]:
    """Chain one or more MBOX files into a single email iterator with
    incremental resume.

    For each MBOX path we look up `mbox_state` in SQLite to know where the
    previous run stopped. If the file has grown, we seek to that offset and
    only yield the new tail. If the file has SHRUNK (Thunderbird Compact
    Folders), we reset to 0 and re-scan. The pipeline updates the cursor
    after each email is committed.
    """
    settings = settings or get_settings()
    init_db(settings.db_path)

    cutoff: datetime | None = None
    if since_days is not None and since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        logger.info("Filter: keep only mails newer than %s", cutoff.isoformat())

    def _stream() -> Iterator[RawEmail]:
        kept = 0
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            if not path.is_file():
                logger.error("MBOX path not found: %s", path)
                continue

            abs_path = str(path.resolve())
            stat = path.stat()
            current_size = stat.st_size

            start_offset = 0
            with connect(settings.db_path) as conn:
                state = get_mbox_state(conn, abs_path)
            if state is not None:
                if current_size < state["last_size"]:
                    logger.warning(
                        "MBOX %s shrank (%d -> %d bytes) - Thunderbird Compact suspected, "
                        "full re-scan from offset 0.",
                        path.name,
                        state["last_size"],
                        current_size,
                    )
                    start_offset = 0
                else:
                    start_offset = state["last_offset"]
                    logger.info(
                        "MBOX %s resume: offset=%d (file %d bytes, +%d new)",
                        path.name,
                        start_offset,
                        current_size,
                        current_size - state["last_size"],
                    )
            else:
                logger.info("MBOX %s: first scan (%d bytes)", path.name, current_size)

            tag = path.parent.name or path.stem
            for mail in read_mbox(path, since=cutoff, start_offset=start_offset):
                kept += 1
                if kept % 50 == 0:
                    logger.info("MBOX progress: %d mails yielded", kept)
                yield RawEmail(
                    uid=f"{tag}:mbox-{mail.mbox_offset}",
                    message_id=mail.message_id,
                    subject=mail.subject,
                    sender=mail.sender,
                    received_at=mail.received_at,
                    body_text=mail.body_text,
                    body_html=mail.body_html,
                    has_attachment=mail.has_attachment,
                    mbox_path=abs_path,
                    mbox_offset=mail.mbox_offset,
                )
        logger.info("MBOX done: %d mails kept", kept)

    return _stream()
