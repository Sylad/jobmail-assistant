from __future__ import annotations

import re

from bs4 import BeautifulSoup

_WS_RUN = re.compile(r"[ \t]+")
_NL_RUN = re.compile(r"\n{3,}")
_QUOTED_LINE = re.compile(r"^>.*$", re.MULTILINE)


_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "head", "meta", "title"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except Exception:
        # Malformed HTML (bad CDATA, unclosed tags, weird encoding) — fall back
        # to a brutal tag-strip regex so one rotten mail can't abort the pipeline.
        text = _TAG_RE.sub(" ", html)
    return _normalize(text)


def normalize_body(text: str) -> str:
    """Strip quotes/signatures noise to keep filter+LLM focused on the new content."""
    text = _QUOTED_LINE.sub("", text)
    return _normalize(text)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RUN.sub(" ", text)
    text = _NL_RUN.sub("\n\n", text)
    return text.strip()
