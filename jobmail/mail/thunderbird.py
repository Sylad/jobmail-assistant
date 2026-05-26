from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..models import RawEmail
from .mbox_reader import iter_with_offsets
from .parser import html_to_text, normalize_body


def read_mbox(
    path: Path,
    *,
    since: datetime | None = None,
    start_offset: int = 0,
) -> Iterator[RawEmail]:
    """Stream a Thunderbird MBOX file.

    - `since` skips mails older than the given timestamp (after the cheap
      header-only date parse, so we don't pay body extraction for old mails).
    - `start_offset` resumes from a given byte offset in the file for
      incremental reads. Pass 0 for a full scan.

    Each yielded RawEmail carries `mbox_path` and `mbox_offset`, which the
    pipeline uses to persist the resume cursor in the `mbox_state` table.
    """
    abs_path = str(path)
    for offset, msg in iter_with_offsets(path, start_offset=start_offset):
        received_at = _parse_date(msg.get("Date", ""))
        if since is not None:
            ref = received_at if received_at.tzinfo else received_at.replace(tzinfo=since.tzinfo)
            if ref < since:
                continue

        body_text, body_html = _extract_bodies(msg)
        yield RawEmail(
            uid=f"mbox-{offset}",
            message_id=_decode_hdr(msg.get("Message-Id", f"mbox-{offset}@local")),
            subject=_decode_hdr(msg.get("Subject", "")),
            sender=_decode_hdr(msg.get("From", "")),
            received_at=received_at,
            body_text=normalize_body(body_text),
            body_html=body_html,
            mbox_path=abs_path,
            mbox_offset=offset,
        )


def _parse_date(raw: str) -> datetime:
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if dt is None:
        return datetime.now(timezone.utc)
    return dt


def _extract_bodies(msg) -> tuple[str, str]:
    text, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and not text:
                text = _decode(part)
            elif ctype == "text/html" and not html:
                html = _decode(part)
    else:
        if msg.get_content_type() == "text/html":
            html = _decode(msg)
        else:
            text = _decode(msg)
    if not text and html:
        text = html_to_text(html)
    return text, html


def _decode_hdr(value) -> str:
    """RFC 2047 decode + force to str. Mail headers can be Header objects
    with =?UTF-8?Q?...?= encoded chunks; sqlite refuses non-str bindings."""
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except (LookupError, UnicodeDecodeError, ValueError):
        return str(value)


def _decode(part) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")
