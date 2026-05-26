"""Low-level MBOX streaming reader with byte-offset reporting.

Why not stdlib `mailbox.mbox`?
- It builds a TOC of the whole file before yielding the first message; on a
  1+ GB MBOX over /mnt/c that's painfully slow.
- It does not expose the byte offset of each message in a stable, public way,
  which we need for incremental resume.

This reader assumes MBOXO format (no `>From ` escaping in bodies) which is
what Thunderbird produces for POP3 INBOX files.
"""
from __future__ import annotations

import email
import re
from collections.abc import Iterator
from email.message import Message
from email.policy import compat32 as email_policy
from pathlib import Path

# A new message starts at the beginning of a line with literal "From ".
# Thunderbird (POP3) writes a minimal envelope `From \r\n` with no sender or
# date, while traditional servers write `From sender@host Mon Jan 01 ...`.
# We match both, then verify by peeking that the next non-empty line looks
# like an RFC 822 header (`Header-Name: value`).
_FROM_LINE = re.compile(rb"^From ")
_RFC822_HEADER = re.compile(rb"^[A-Za-z][A-Za-z0-9-]*:\s")


def iter_with_offsets(path: Path, start_offset: int = 0) -> Iterator[tuple[int, Message]]:
    """Stream (byte_offset, parsed_message) tuples from an MBOX file.

    `start_offset` lets the caller resume from a known good position. If the
    offset is mid-message, we skip ahead to the next valid envelope. The
    returned offsets are absolute and point to the `From ` separator line of
    each message.
    """
    with path.open("rb") as fh:
        if start_offset > 0:
            fh.seek(start_offset)
            here = fh.tell()
            line = fh.readline()
            if not line:
                return
            if not _is_envelope(fh, line):
                _advance_to_next_envelope(fh)
            else:
                fh.seek(here)  # rewind so the loop below sees the From line

        msg_offset = fh.tell()
        msg_buf: list[bytes] = []
        first = True

        while True:
            pos_before = fh.tell()
            line = fh.readline()
            if not line:
                break
            if not first and _FROM_LINE.match(line) and _is_envelope(fh, line):
                yield msg_offset, _parse(b"".join(msg_buf))
                msg_offset = pos_before
                msg_buf = [line]
            else:
                msg_buf.append(line)
                first = False

        if msg_buf:
            yield msg_offset, _parse(b"".join(msg_buf))


def _is_envelope(fh, line: bytes) -> bool:
    """Confirm that `line` (which starts with 'From ') is a real MBOX envelope:
    the next non-empty line within the next few lines must look like an
    RFC 822 header. Otherwise it's a body line that happens to begin with
    'From '. Restores the file cursor before returning."""
    if not _FROM_LINE.match(line):
        return False
    pos = fh.tell()
    try:
        for _ in range(6):
            next_line = fh.readline()
            if not next_line:
                return False
            stripped = next_line.strip()
            if not stripped:
                continue
            return _RFC822_HEADER.match(next_line) is not None
        return False
    finally:
        fh.seek(pos)


def _advance_to_next_envelope(fh) -> None:
    """Read lines until the next valid envelope, then position the cursor at
    the start of that envelope line."""
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            return
        if _FROM_LINE.match(line) and _is_envelope(fh, line):
            fh.seek(pos)
            return


def _advance_to_next_from(fh) -> None:
    """Read lines until the next `From ` envelope, then position the cursor at
    the start of that line (so the main loop sees it)."""
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            return  # EOF
        if _FROM_LINE.match(line):
            fh.seek(pos)
            return


def _parse(raw: bytes) -> Message:
    # MBOX prefixes each message with "From ..." envelope line; strip it before
    # parsing so the email module sees a clean RFC 5322 message.
    if raw.startswith(b"From "):
        nl = raw.find(b"\n")
        if nl >= 0:
            raw = raw[nl + 1 :]
    return email.message_from_bytes(raw, policy=email_policy)
