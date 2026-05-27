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


def extract_offer_links(
    body_text: str = "",
    body_html: str = "",
    *,
    max_links: int = 5,
    preferred_terms: list[str] | None = None,
) -> list[OfferLink]:
    links: list[OfferLink] = []

    if body_html:
        links.extend(_links_from_html(body_html))
    if body_text:
        links.extend(OfferLink(url=url, label="Lien du mail") for url in URL_RE.findall(body_text))

    deduped_by_url: dict[str, OfferLink] = {}
    for link in links:
        url = _normalize_offer_url(_clean_url(_unwrap_tracking_url(link.url)))
        if not _is_http_url(url):
            continue
        clean_link = OfferLink(url=url, label=_clean_label(link.label, url))
        previous = deduped_by_url.get(url)
        if previous is None or _label_quality(clean_link.label, url) > _label_quality(previous.label, url):
            deduped_by_url[url] = clean_link
    return sorted(deduped_by_url.values(), key=lambda link: _offer_link_rank(link, preferred_terms or []))[:max_links]


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


def _normalize_offer_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host.endswith("linkedin.com") and parsed.path.startswith("/comm/jobs/view/"):
        return parsed._replace(path=parsed.path.removeprefix("/comm"), query="").geturl()
    return url


def _offer_link_rank(link: OfferLink, preferred_terms: list[str]) -> tuple[int, str]:
    parsed = urlparse(link.url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    label = link.label.lower()
    preferred_score = sum(1 for term in preferred_terms if term and term.lower() in label)

    if host.endswith("linkedin.com") and "/jobs/view/" in path:
        return (0, -preferred_score, link.url)
    if any(part in path for part in ("/jobs/", "/job/", "/careers/", "/career/", "/offres/", "/offer")):
        return (1, -preferred_score, link.url)
    if any(word in label for word in ("offre", "poste", "emploi", "job", "candidater", "apply")):
        return (2, -preferred_score, link.url)
    if any(part in path for part in ("/feed", "/messaging", "/mynetwork", "/notifications", "/premium", "/help", "unsubscribe")):
        return (8, -preferred_score, link.url)
    return (5, -preferred_score, link.url)


def _label_quality(label: str, url: str) -> int:
    host = urlparse(url).netloc.removeprefix("www.")
    if not label or label == host:
        return 0
    return min(len(label), 120)
