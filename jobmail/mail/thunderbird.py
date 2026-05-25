from __future__ import annotations

import mailbox
from collections.abc import Iterator
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..models import RawEmail
from .parser import html_to_text, normalize_body


def read_mbox(path: Path) -> Iterator[RawEmail]:
    """Read a Thunderbird MBOX file (e.g. exported via ImportExportTools NG).

    Thunderbird's profile stores INBOX as an MBOX file at:
      %APPDATA%/Thunderbird/Profiles/<id>/ImapMail/<server>/INBOX
    Pass that path here.
    """
    mbox = mailbox.mbox(str(path))
    for i, msg in enumerate(mbox):
        body_text, body_html = _extract_bodies(msg)
        received_raw = msg.get("Date", "")
        try:
            received_at = parsedate_to_datetime(received_raw)
        except (TypeError, ValueError):
            received_at = datetime.now()
        yield RawEmail(
            uid=f"mbox-{i}",
            message_id=_decode_hdr(msg.get("Message-Id", f"mbox-{i}@local")),
            subject=_decode_hdr(msg.get("Subject", "")),
            sender=_decode_hdr(msg.get("From", "")),
            received_at=received_at,
            body_text=normalize_body(body_text),
            body_html=body_html,
        )


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
