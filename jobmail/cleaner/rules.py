from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SAFETY_KEYWORDS = [
    "facture",
]

PROMOTIONAL_SENDER_PATTERNS = [
    r"newsletter",
    r"news@",
    r"no-?reply@",
    r"noreply@",
    r"promo",
    r"marketing",
    r"deal",
    r"offres?",
]

PROMOTIONAL_KEYWORDS = [
    "newsletter",
    "desabonner",
    "désabonner",
    "unsubscribe",
    "soldes",
    "promotion",
    "promo",
    "bon plan",
    "vente privee",
    "vente privée",
    "offre speciale",
    "offre spéciale",
    "black friday",
    "cyber monday",
    "derniere chance",
    "dernière chance",
    "shopping",
]


@dataclass(slots=True, frozen=True)
class CleanerDecision:
    is_candidate: bool
    reason: str = ""
    safety_hit: str = ""


def classify_cleaner_candidate(subject: str, body: str, sender: str, *, has_attachment: bool = False) -> CleanerDecision:
    haystack = _normalize(f"{sender}\n{subject}\n{body}")
    safety_hit = _first_keyword(haystack, SAFETY_KEYWORDS)
    if safety_hit and has_attachment:
        return CleanerDecision(False, safety_hit=safety_hit)

    sender_norm = _normalize(sender)
    for pattern in PROMOTIONAL_SENDER_PATTERNS:
        if re.search(pattern, sender_norm):
            return CleanerDecision(True, f"expediteur promotionnel: {pattern}")

    promo_hit = _first_keyword(haystack, PROMOTIONAL_KEYWORDS)
    if promo_hit:
        return CleanerDecision(True, f"mot-cle promotionnel: {promo_hit}")

    return CleanerDecision(False)


def _first_keyword(haystack: str, keywords: list[str]) -> str:
    for keyword in keywords:
        kw = _normalize(keyword)
        pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            return keyword
    return ""


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text
