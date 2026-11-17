from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timezone
from email.header import Header, decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..models import RawEmail
from .mbox_reader import iter_with_offsets
from .parser import html_to_text, normalize_body

_ENCODED_WORD = re.compile(r"=\?[^?\s]+\?[bBqQ]\?[^?\s]*\?=")
_BETWEEN_WORDS = re.compile(r"(?<=\?=)[ \t\r\n]+(?==\?[^?\s]+\?[bBqQ]\?)")


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
        charset = _declared_charset(msg)
        yield RawEmail(
            uid=f"mbox-{offset}",
            message_id=_decode_hdr(msg.get("Message-Id", f"mbox-{offset}@local"), charset),
            subject=_decode_hdr(msg.get("Subject", ""), charset),
            sender=_decode_hdr(msg.get("From", ""), charset),
            received_at=received_at,
            body_text=normalize_body(body_text),
            body_html=body_html,
            has_attachment=_has_attachment(msg),
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


def _has_attachment(msg) -> bool:
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            return True
    return False


def _declared_charset(msg) -> str | None:
    """Charset declared by the message (its own Content-Type, else the first
    text part). Used as a hint for raw 8-bit headers."""
    charset = msg.get_content_charset()
    if charset or not msg.is_multipart():
        return charset
    for part in msg.walk():
        if part.get_content_maintype() == "text" and part.get_content_charset():
            return part.get_content_charset()
    return None


def _decode_bytes(raw: bytes, *charsets: str | None) -> str:
    """Decode with UTF-8 first, then each given charset, latin-1 last (never fails)."""
    for charset in ("utf-8", *charsets):
        if not charset:
            continue
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("latin-1")


def _decode_word(match: re.Match, declared: str | None) -> str:
    word = match.group(0)
    try:
        raw, charset = decode_header(word)[0]
    except (ValueError, LookupError):  # malformed base64: keep the word as is
        return word
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode(charset or "ascii")
    except (LookupError, UnicodeDecodeError):
        return _decode_bytes(raw, declared)


def _decode_hdr(value, charset: str | None = None) -> str:
    """Header value to str (sqlite refuses non-str bindings).

    Handles RFC 2047 encoded words (=?UTF-8?Q?...?=) AND raw 8-bit bytes that
    some senders put in headers without encoding them. With the compat32
    policy, such a header comes back as a Header object whose str() replaces
    every non-ASCII byte with U+FFFD; we recover the original bytes and try
    UTF-8, then `charset` (the one the message declares), then latin-1.
    """
    if value is None:
        return ""
    if isinstance(value, Header):
        # Header built by the parser from raw 8-bit bytes: get the bytes back.
        text = "".join(
            _decode_bytes(chunk, charset) if isinstance(chunk, bytes) else chunk
            for chunk, _ in decode_header(value)
        )
    else:
        text = str(value)
        if any("\udc80" <= ch <= "\udcff" for ch in text):  # surrogateescape'd bytes
            text = _decode_bytes(text.encode("utf-8", "surrogateescape"), charset)
    # RFC 2047: whitespace between two adjacent encoded words is not displayed.
    text = _BETWEEN_WORDS.sub("", text)
    return _ENCODED_WORD.sub(lambda m: _decode_word(m, charset), text)


def _decode(part) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")
