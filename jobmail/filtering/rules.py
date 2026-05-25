from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Keywords are matched as whole words, case- and accent-insensitive.
# Two categories: "intent" (the mail is *about* a job opening) and
# "techno" (the mail mentions one of my technologies). A mail is
# considered job_related when (intent ≥ 1) OR (intent ≥ 0 AND techno ≥ 2).

JOB_INTENT_KEYWORDS = [
    "recrutement", "recruteur", "recruteuse", "recruiter", "recruiting",
    "opportunite", "opportunity", "opportunities",
    "poste", "position", "role", "job",
    "mission", "missions",
    "emploi", "employment", "hiring", "hire",
    "candidature", "candidate", "application",
    "freelance", "consultant", "consulting",
    "cdi", "cdd", "contractor", "permanent",
    "remote", "teletravail", "hybride", "hybrid", "onsite", "on-site",
    "salaire", "salary", "tjm", "package",
    "linkedin", "welcome to the jungle", "apec", "indeed", "monster",
    "offre d'emploi", "offre demploi", "job offer",
]

TECHNO_KEYWORDS = [
    "java", "spring", "spring boot", "springboot",
    "kubernetes", "k8s", "docker", "helm", "argocd",
    "geoserver", "geotools", "geonetwork",
    "sig", "gis", "openlayers", "leaflet", "mapbox", "maplibre",
    "postgis", "postgresql", "postgres",
    "kafka", "rabbitmq", "elasticsearch",
    "angular", "react", "nestjs", "typescript",
    "python", "fastapi", "django",
    "aws", "azure", "gcp",
    "devops", "sre", "platform engineer",
]


@dataclass(slots=True, frozen=True)
class FilterResult:
    is_job_related: bool
    matched_intent: list[str]
    matched_technos: list[str]

    @property
    def all_matches(self) -> list[str]:
        return [*self.matched_intent, *self.matched_technos]


def classify(subject: str, body: str) -> FilterResult:
    haystack = _normalize(f"{subject}\n{body}")
    intent = _find_matches(haystack, JOB_INTENT_KEYWORDS)
    technos = _find_matches(haystack, TECHNO_KEYWORDS)

    is_job = bool(intent) or len(technos) >= 2
    return FilterResult(
        is_job_related=is_job,
        matched_intent=intent,
        matched_technos=technos,
    )


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def _find_matches(haystack: str, vocabulary: list[str]) -> list[str]:
    found: list[str] = []
    for kw in vocabulary:
        kw_norm = _normalize(kw)
        # Word boundary on either side; allow phrase keywords with spaces.
        pattern = r"(?<![a-z0-9])" + re.escape(kw_norm) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            found.append(kw)
    return found
