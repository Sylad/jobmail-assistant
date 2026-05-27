from __future__ import annotations

import hashlib
import re

from ..filtering.rules import TECHNO_KEYWORDS
from ..models import ContractType, OfferExtraction, RawEmail, WorkMode
from .base import LocalLLMProvider


class MockProvider(LocalLLMProvider):
    """Deterministic, offline extractor — never touches a network.

    Good enough for V1 demo + tests. Pulls heuristics from subject+body so
    the dashboard shows plausibly-varied data on real mails too."""

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        text = f"{email.subject}\n{email.body_text}"
        text_l = text.lower()

        technos = [kw for kw in TECHNO_KEYWORDS if _has_word(text_l, kw)]
        work_mode = _detect_work_mode(text_l)
        contract = _detect_contract(text_l)
        english = bool(re.search(r"\b(english|anglais)\b", text_l))

        company = _guess_company(email.sender)
        title = _guess_title(email.subject)

        score = _score(technos, target_profile, work_mode)
        summary = _summary(email.subject, technos, work_mode, contract)

        return OfferExtraction(
            title=title,
            company=company,
            recruiter=email.sender,
            location=_guess_location(text),
            work_mode=work_mode,
            technos=technos,
            english_required=english,
            contract_type=contract,
            summary=summary,
            offer_url=_first_url(email.body_text),
            relevance_score=score,
        )


def _has_word(text: str, kw: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", text) is not None


def _detect_work_mode(text_l: str) -> WorkMode:
    if re.search(r"\b(full[- ]?remote|100% remote|teletravail total)\b", text_l):
        return WorkMode.REMOTE
    if re.search(r"\b(hybrid|hybride|2 jours|3 jours)\b", text_l):
        return WorkMode.HYBRID
    if re.search(r"\b(on[- ]?site|presentiel|sur site)\b", text_l):
        return WorkMode.ONSITE
    if "remote" in text_l or "teletravail" in text_l:
        return WorkMode.REMOTE
    return WorkMode.UNKNOWN


def _detect_contract(text_l: str) -> ContractType:
    if "freelance" in text_l or "tjm" in text_l:
        return ContractType.FREELANCE
    if "mission" in text_l:
        return ContractType.MISSION
    if "cdi" in text_l:
        return ContractType.CDI
    if "cdd" in text_l:
        return ContractType.CDD
    return ContractType.UNKNOWN


def _guess_company(sender: str) -> str:
    m = re.search(r"@([\w-]+)\.", sender)
    if m:
        return m.group(1).capitalize()
    m = re.match(r'"?([^"<@]+)"?\s*<', sender)
    if m:
        return m.group(1).strip()
    return sender.split("@")[0] if sender else ""


def _guess_title(subject: str) -> str:
    # Strip common prefixes
    s = re.sub(r"^(re|fwd|tr|fw)\s*:\s*", "", subject, flags=re.IGNORECASE).strip()
    return s[:120]


def _guess_location(text: str) -> str:
    cities = ["Paris", "Lyon", "Lille", "Toulouse", "Nantes", "Bordeaux",
              "Marseille", "Strasbourg", "Rennes", "Sophia Antipolis",
              "Grenoble", "Montpellier", "Remote", "Berlin", "London", "Amsterdam"]
    for c in cities:
        if re.search(r"\b" + re.escape(c) + r"\b", text, re.IGNORECASE):
            return c
    return ""


def _score(technos: list[str], target_profile: str, work_mode: WorkMode) -> int:
    target_l = target_profile.lower()
    target_kws = re.findall(r"[a-z]+", target_l)
    target_set = {k for k in target_kws if len(k) > 2}

    hits = sum(1 for t in technos if any(p in t.lower() for p in target_set))
    score = min(10, hits * 2)
    if work_mode in (WorkMode.REMOTE, WorkMode.HYBRID):
        score = min(10, score + 1)
    return score


def _summary(subject: str, technos: list[str], wm: WorkMode, ct: ContractType) -> str:
    parts = []
    if technos:
        parts.append("Stack: " + ", ".join(technos[:6]))
    if wm is not WorkMode.UNKNOWN:
        parts.append(f"Mode: {wm.value}")
    if ct is not ContractType.UNKNOWN:
        parts.append(f"Contrat: {ct.value}")
    head = "; ".join(parts) if parts else "Pas de détails clairs."
    return f"{subject[:80]} — {head}".strip()


def _first_url(text: str) -> str:
    match = re.search(r"https?://[^\s<>'\")]+", text)
    return match.group(0).rstrip(".,;:)]}") if match else ""


# Deterministic hash used by tests to assert idempotency.
def _deterministic_id(email: RawEmail) -> str:
    return hashlib.sha1(email.fingerprint.encode("utf-8")).hexdigest()[:12]


MockExtractor = MockProvider
