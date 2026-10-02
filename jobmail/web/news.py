"""Nouveautés — journal des évolutions visibles de l'application (signature commune des apps).

Source : `docs/nouveautes/*.md` (une entrée par changement, avec ses captures), compilée par
`cadence news build` dans `jobmail/web/static/nouveautes-data/` (nouveautes.json + captures),
**versionnée** : un `git clone` suivi de `jobmail serve` fonctionne sans le CLI cadence. Le
script `scripts/build-news.sh` régénère ce dossier ; `tests/test_news_web.py` échoue si le
JSON versionné ne suit plus `docs/nouveautes/`.

La page lit le JSON à chaque requête (quelques Ko) : une entrée ajoutée apparaît sans
redémarrer le serveur. Le corps des entrées est du HTML produit par cadence (texte échappé,
liens http(s)/mailto/relatifs seulement) ; il est de nouveau filtré ici par une liste blanche
(`sanitize_news_html`) avant d'être inséré tel quel, pour qu'un JSON modifié à la main ne
puisse pas injecter de balise ou d'attribut.
"""
from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from pathlib import Path

NEWS_DATA_DIR = Path(__file__).parent / "static" / "nouveautes-data"
NEWS_URL_BASE = "/static/nouveautes-data"

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CAPTURE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*\.(?:png|jpe?g|webp|gif)$", re.I)


@dataclass
class Capture:
    url: str
    alt: str
    width: int | None = None
    height: int | None = None


@dataclass
class NewsEntry:
    slug: str
    title: str
    date: str
    html: str
    captures: list[Capture] = field(default_factory=list)
    lots: list[str] = field(default_factory=list)


@dataclass
class NewsData:
    entries: list[NewsEntry]
    error: str = ""


# ── Corps des entrées : liste blanche ────────────────────────────────────────────

_ALLOWED = {"p", "ul", "ol", "li", "strong", "em", "code", "a", "br"}
_VOID = {"br"}
_DROP_CONTENT = {"script", "style", "template", "iframe", "object", "noscript", "textarea"}


def _safe_url(url: str) -> bool:
    if re.search(r"[\x00-\x20\x7f]", url):
        return False
    if re.match(r"^(?:https?://|mailto:)", url, re.I):
        return True
    return not re.match(r"^[a-z][\w+.-]*:", url, re.I)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self.dropping += 1
            return
        if self.dropping or tag not in _ALLOWED:
            return
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v is not None), None)
            if href is None or not _safe_url(href):
                self.stack.append("a:skip")
                return
            self.out.append(f'<a href="{escape(href, quote=True)}">')
        else:
            self.out.append(f"<{tag}>")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _DROP_CONTENT:
            self.dropping -= 1

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping or tag not in _ALLOWED or tag in _VOID:
            return
        names = [t.split(":")[0] for t in self.stack]
        if tag not in names:
            return
        while self.stack:
            top = self.stack.pop()
            if top != "a:skip":
                self.out.append(f"</{top}>")
            if top.split(":")[0] == tag:
                break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(escape(data, quote=False))

    def close(self):
        super().close()
        while self.stack:
            top = self.stack.pop()
            if top != "a:skip":
                self.out.append(f"</{top}>")


def sanitize_news_html(html: object) -> str:
    """HTML de cadence → seulement p, ul, ol, li, strong, em, code, br et a[href sûr]."""
    if not isinstance(html, str):
        return ""
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    return "".join(parser.out)


# ── Captures ─────────────────────────────────────────────────────────────────────

def image_size(path: Path) -> tuple[int, int] | None:
    """Largeur et hauteur lues dans l'en-tête PNG ou GIF (réservent la place, pas de saut)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(26)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return struct.unpack(">II", head[16:24])
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", head[6:10])
    return None


def _captures(raw: object, title: str, data_dir: Path) -> list[Capture]:
    names = [c for c in raw if isinstance(c, str)] if isinstance(raw, list) else []
    names = [c for c in names if _CAPTURE.match(c) and ".." not in c.split("/")]
    out = []
    for i, name in enumerate(names, start=1):
        alt = (
            f"Capture d'écran {i} sur {len(names)} : {title}"
            if len(names) > 1
            else f"Capture d'écran : {title}"
        )
        size = image_size(data_dir / name)
        out.append(
            Capture(
                url=f"{NEWS_URL_BASE}/{name}",
                alt=alt,
                width=size[0] if size else None,
                height=size[1] if size else None,
            )
        )
    return out


# ── Lecture ──────────────────────────────────────────────────────────────────────

UNREADABLE = "Le journal des nouveautés est illisible pour le moment."


def load_news(data_dir: Path | None = None) -> NewsData:
    """Entrées dans l'ordre donné par cadence (date puis heure de création, plus récente d'abord).

    Dossier ou fichier absent = aucune entrée publiée ; JSON illisible = message d'erreur
    honnête (jamais une page blanche ni une erreur 500).
    """
    data_dir = data_dir or NEWS_DATA_DIR
    path = data_dir / "nouveautes.json"
    if not path.exists():
        return NewsData(entries=[])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = payload["entries"]
        if not isinstance(raw_entries, list):
            raise TypeError("entries")
    except (OSError, ValueError, KeyError, TypeError):
        return NewsData(entries=[], error=UNREADABLE)
    entries = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        slug, title, day = raw.get("slug"), raw.get("title"), raw.get("date")
        if not (isinstance(slug, str) and slug and isinstance(title, str) and title.strip()):
            continue
        if not (isinstance(day, str) and _DAY.match(day)) or slug in seen:
            continue
        seen.add(slug)
        lots = [str(x) for x in raw.get("lots", []) if isinstance(x, str | int)] if isinstance(
            raw.get("lots"), list
        ) else []
        entries.append(
            NewsEntry(
                slug=slug,
                title=title.strip(),
                date=day,
                html=sanitize_news_html(raw.get("html")),
                captures=_captures(raw.get("captures"), title.strip(), data_dir),
                lots=lots,
            )
        )
    return NewsData(entries=entries)


def news_index(data_dir: Path | None = None) -> list[dict[str, str]]:
    """Slugs et dates de toutes les entrées : la pastille du menu en a besoin sur chaque page."""
    return [{"slug": e.slug, "date": e.date} for e in load_news(data_dir).entries]


def news_titles_by_lot(entries: list[NewsEntry]) -> dict[str, str]:
    """Titre de la première entrée (la plus récente) qui cite chaque lot."""
    titles: dict[str, str] = {}
    for e in entries:
        for lot in e.lots:
            titles.setdefault(lot, e.title)
    return titles
