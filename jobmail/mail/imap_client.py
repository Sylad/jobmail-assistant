from __future__ import annotations

import logging
from collections.abc import Iterator

from imap_tools import AND, MailBox

from ..config import Settings
from ..models import RawEmail
from .parser import html_to_text, normalize_body

logger = logging.getLogger(__name__)


def fetch_recent(settings: Settings) -> Iterator[RawEmail]:
    """Yield recent emails from IMAP. Bail out silently if IMAP not configured."""
    if not settings.imap_enabled:
        logger.info("IMAP disabled (no host/user/password). Skipping fetch.")
        return

    with MailBox(settings.imap_host, port=settings.imap_port).login(
        settings.imap_user, settings.imap_password, initial_folder=settings.imap_folder
    ) as mailbox:
        msgs = mailbox.fetch(
            AND(all=True),
            limit=settings.imap_fetch_limit,
            reverse=True,
            mark_seen=False,
        )
        for msg in msgs:
            body_text = (msg.text or "").strip()
            body_html = msg.html or ""
            if not body_text and body_html:
                body_text = html_to_text(body_html)
            yield RawEmail(
                uid=str(msg.uid),
                message_id=msg.headers.get("message-id", (msg.uid,))[0],
                subject=msg.subject or "",
                sender=msg.from_ or "",
                received_at=msg.date,
                body_text=normalize_body(body_text),
                body_html=body_html,
                has_attachment=bool(getattr(msg, "attachments", [])),
            )
