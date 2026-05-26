from __future__ import annotations

import re

from .models import RawEmail

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d .()/\-]{7,}\d)(?!\d)")
URL_RE = re.compile(r"https?://[^\s<>\"]+")


def anonymize_text(text: str) -> str:
    """Remove direct personal identifiers before cloud LLM calls."""
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = PHONE_RE.sub("[redacted-phone]", text)
    text = URL_RE.sub("[redacted-url]", text)
    return text


def anonymize_email(email: RawEmail) -> RawEmail:
    """Return a copy safe enough for cloud payload construction."""
    return RawEmail(
        uid=email.uid,
        message_id=email.message_id,
        subject=anonymize_text(email.subject),
        sender="[redacted-email]" if EMAIL_RE.search(email.sender) else anonymize_text(email.sender),
        received_at=email.received_at,
        body_text=anonymize_text(email.body_text),
        body_html="",
    )
