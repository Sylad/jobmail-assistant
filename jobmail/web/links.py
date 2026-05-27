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
    preferred_url: str = "",
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
    normalized_preferred_url = _normalize_offer_url(_clean_url(_unwrap_tracking_url(preferred_url)))
    if normalized_preferred_url not in deduped_by_url:
        normalized_preferred_url = ""
    return sorted(
        deduped_by_url.values(),
        key=lambda link: _offer_link_rank(link, preferred_terms or [], normalized_preferred_url),
    )[:max_links]


def build_preferred_offer_terms(*values: str) -> list[str]:
    terms: list[str] = []
    for value in values:
        text = " ".join((value or "").replace("\xa0", " ").split())
        if not text:
            continue
        terms.append(text)
        if " chez " in text.lower():
            left, right = re.split(r"\s+chez\s+", text, maxsplit=1, flags=re.IGNORECASE)
            terms.extend([left.strip(), right.strip()])
        if " recherche " in text.lower():
            left, right = re.split(r"\s+recherche\s+", text, maxsplit=1, flags=re.IGNORECASE)
            terms.extend([left.strip(), right.strip()])
    clean_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = re.sub(r"\s+-\s+Jobs\s*:.*$", "", term, flags=re.IGNORECASE).strip(" -")
        if len(cleaned) < 4:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        clean_terms.append(cleaned)
    return clean_terms


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


def _offer_link_rank(link: OfferLink, preferred_terms: list[str], preferred_url: str = "") -> tuple[int, int, str]:
    parsed = urlparse(link.url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    label = link.label.lower()
    preferred_score = _preferred_score(label, preferred_terms)

    if preferred_url and link.url == preferred_url:
        return (-1, -preferred_score, link.url)
    if host.endswith("linkedin.com") and "/jobs/view/" in path:
        return (0, -preferred_score, link.url)
    if any(part in path for part in ("/jobs/", "/job/", "/careers/", "/career/", "/offres/", "/offer")):
        return (1, -preferred_score, link.url)
    if any(word in label for word in ("offre", "poste", "emploi", "job", "candidater", "apply")):
        return (2, -preferred_score, link.url)
    if any(part in path for part in ("/feed", "/messaging", "/mynetwork", "/notifications", "/premium", "/help", "unsubscribe")):
        return (8, -preferred_score, link.url)
    return (5, -preferred_score, link.url)


def _preferred_score(label: str, preferred_terms: list[str]) -> int:
    score = 0
    for term in build_preferred_offer_terms(*preferred_terms):
        term_l = term.lower()
        if term_l in label:
            score += 20
            continue
        words = [word for word in re.findall(r"[\wÀ-ÿ+#.-]+", term_l) if len(word) >= 4]
        score += sum(1 for word in words if word in label)
    return score


def _label_quality(label: str, url: str) -> int:
    host = urlparse(url).netloc.removeprefix("www.")
    if not label or label == host:
        return 0
    return min(len(label), 120)
