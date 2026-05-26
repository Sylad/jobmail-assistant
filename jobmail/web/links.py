from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
TRACKING_PARAMS = ("url", "u", "target", "redirect", "redirect_url", "destination", "link")


@dataclass(slots=True, frozen=True)
class OfferLink:
    url: str
    label: str


def extract_offer_links(body_text: str = "", body_html: str = "", *, max_links: int = 5) -> list[OfferLink]:
    links: list[OfferLink] = []

    if body_html:
        links.extend(_links_from_html(body_html))
    if body_text:
        links.extend(OfferLink(url=url, label="Lien du mail") for url in URL_RE.findall(body_text))

    deduped: list[OfferLink] = []
    seen: set[str] = set()
    for link in links:
        url = _clean_url(_unwrap_tracking_url(link.url))
        if not _is_http_url(url) or url in seen:
            continue
        seen.add(url)
        deduped.append(OfferLink(url=url, label=_clean_label(link.label, url)))
        if len(deduped) >= max_links:
            break
    return deduped


def _links_from_html(body_html: str) -> list[OfferLink]:
    soup = BeautifulSoup(body_html, "html.parser")
    links: list[OfferLink] = []
    for tag in soup.find_all("a", href=True):
        href = str(tag.get("href", "")).strip()
        label = tag.get_text(" ", strip=True)
        links.append(OfferLink(url=href, label=label))
    return links


def _unwrap_tracking_url(url: str) -> str:
    parsed = urlparse(unescape(url))
    qs = parse_qs(parsed.query)
    for key in TRACKING_PARAMS:
        values = qs.get(key)
        if not values:
            continue
        candidate = unquote(values[0])
        if _is_http_url(candidate):
            return candidate
    return url


def _clean_url(url: str) -> str:
    return unescape(url).strip().rstrip(".,;:)]}")


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _clean_label(label: str, url: str) -> str:
    label = " ".join(label.split())
    if not label or len(label) > 80:
        host = urlparse(url).netloc.removeprefix("www.")
        return host or "Voir l'offre"
    return label
