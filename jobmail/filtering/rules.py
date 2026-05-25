from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Four layers of signal, evaluated in order :
#   0. RECRUITER_SENDER_PATTERNS → auto-positive (job boards, ATS, in-mails)
#   1. NOISE_SENDER_PATTERNS     → auto-negative (gaming/e-commerce newsletters)
#   2. STRONG_INTENT_KEYWORDS    → phrases or unambiguous tokens; 1 hit = job
#   3. WEAK_INTENT_KEYWORDS      → ambiguous tokens; combine with a techno
#   4. TECHNO_KEYWORDS           → my stack; 2+ alone is enough
#
# Final rule (after sender shortcuts) :
#   (strong >= 1) OR (weak >= 1 AND techno >= 1) OR (techno >= 2)

# Senders known to deliver recruitment messages. Wins over noise list.
# Patterns are regexes matched against the lowered full From header.
RECRUITER_SENDER_PATTERNS = [
    r"jooble\.org",
    # LinkedIn matched below with a stricter rule that excludes social spam.
    r"welcometothejungle",
    r"indeed\.(com|fr)",
    r"apec\.(fr|com)",
    r"hellowork|monster\.(com|fr)",
    r"cadremploi\.fr",
    r"glassdoor",
    r"hays\.|michaelpage|robert-half|page-personnel|kelly-?services|adecco|manpower|randstad",
    r"talent\.io|malt\.(fr|com)|free-?work|comet\.co",
    r"recruit(er|ing|ment)?@",
    r"@.*\.recrut\w*",
    r"jobs?@|talent@|hr@|rh@|carriere@|career@",
]

# Senders that virtually never carry recruitment offers. Matched against the
# full From header (case-insensitive). Add to this list as false positives
# show up. Regexes, not substring tests, to keep precision.
NOISE_SENDER_PATTERNS = [
    r"xbox\.com",
    r"@.*microsoft\.com",
    r"@.*windows\.com",
    r"stardock(games|entertainment)?",
    r"atari\.com",
    r"steampowered|valvesoftware",
    r"epicgames|ubisoft|ea\.com|playstation|nintendo",
    r"paypal\.fr|paypal\.com",
    r"amazon\.(com|fr)",
    r"ebay\.|aliexpress|cdiscount|fnac\.com|darty",
    r"facebookmail\.com|instagram|tiktok",
    r"youtube|spotify|netflix",
    r"orange.*service.*clients",
    r"booking\.com|airbnb|tripadvisor",
    r"sncf|trainline|ouibus|flixbus",
    r"linkedin\.com.*notifications?",   # LinkedIn notif spam, not InMail
    r"no-?reply@.*game",
    r"newsletter@",
    r"promo|deals?|sale|soldes",
]

# Strong signals — 1 hit = job-related, no need for techno corroboration.
STRONG_INTENT_KEYWORDS = [
    # FR phrases
    "votre candidature", "votre profil", "votre cv",
    "nous recrutons", "nous recherchons", "on recrute", "on recherche",
    "offre d'emploi", "offre demploi", "offre de mission", "offre de poste",
    "proposition d'emploi", "proposition de mission",
    "entretien", "rendez-vous candidat", "test technique",
    "remuneration", "salaire annuel", "package annuel", "tjm",
    # FR single words rares in noise
    "recrutement", "recruteur", "recruteuse",
    "candidature", "candidat", "candidates",
    "freelance", "intercontrat",
    "cdi", "cdd",
    # EN phrases
    "your application", "your candidacy", "your cv", "your resume",
    "we are hiring", "we're hiring", "we are looking", "we're looking",
    "job offer", "job opportunity", "career opportunity",
    "interview", "technical interview", "technical test",
    # EN single words rares in noise
    "recruiter", "recruiting", "hiring",
    # Job boards
    "welcome to the jungle", "welcometothejungle",
    "apec.fr", "indeed", "monster.com",
    "hays", "michael page", "robert half", "page personnel",
]

# Weak signals — common words that need techno corroboration.
WEAK_INTENT_KEYWORDS = [
    "opportunite", "opportunity", "opportunities",
    "poste", "position", "role",
    "mission", "missions",
    "emploi", "employment",
    "consultant", "consulting", "contractor",
    "remote", "teletravail", "hybride", "hybrid", "onsite",
    "salaire", "salary", "package",
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
    matched_strong: list[str]
    matched_weak: list[str]
    matched_technos: list[str]
    sender_is_recruiter: bool = False
    sender_is_noise: bool = False

    @property
    def all_matches(self) -> list[str]:
        tags = [*self.matched_strong, *self.matched_weak, *self.matched_technos]
        if self.sender_is_recruiter:
            tags.insert(0, "sender:recruiter")
        return tags


def classify(subject: str, body: str, sender: str = "") -> FilterResult:
    haystack = _normalize(f"{subject}\n{body}")
    sender_norm = sender.lower()
    subject_norm = _normalize(subject)

    # 0a. LinkedIn special case — accept only when the subject smells like
    #     recruitment, not "X liked your post" / "people viewed your profile".
    if re.search(r"linkedin\.com", sender_norm):
        if _linkedin_subject_is_recruitment(subject_norm):
            strong = _find_matches(haystack, STRONG_INTENT_KEYWORDS)
            technos = _find_matches(haystack, TECHNO_KEYWORDS)
            return FilterResult(
                is_job_related=True,
                matched_strong=strong,
                matched_weak=[],
                matched_technos=technos,
                sender_is_recruiter=True,
            )
        # Social spam — drop.
        return FilterResult(False, [], [], [], sender_is_noise=True)

    # 0b. Other recruiter sender → auto-positive, no other test needed.
    if any(re.search(p, sender_norm) for p in RECRUITER_SENDER_PATTERNS):
        strong = _find_matches(haystack, STRONG_INTENT_KEYWORDS)
        technos = _find_matches(haystack, TECHNO_KEYWORDS)
        return FilterResult(
            is_job_related=True,
            matched_strong=strong,
            matched_weak=[],
            matched_technos=technos,
            sender_is_recruiter=True,
        )

    # 1. Noise sender → auto-negative.
    if any(re.search(p, sender_norm) for p in NOISE_SENDER_PATTERNS):
        return FilterResult(False, [], [], [], sender_is_noise=True)

    # 2–4. Body content check.
    strong = _find_matches(haystack, STRONG_INTENT_KEYWORDS)
    weak = _find_matches(haystack, WEAK_INTENT_KEYWORDS)
    technos = _find_matches(haystack, TECHNO_KEYWORDS)

    is_job = (
        bool(strong)
        or (bool(weak) and bool(technos))
        or len(technos) >= 2
    )
    return FilterResult(
        is_job_related=is_job,
        matched_strong=strong,
        matched_weak=weak,
        matched_technos=technos,
    )


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


LINKEDIN_RECRUITMENT_HINTS = [
    "offre", "offer", "poste", "position", "role", "opportunite", "opportunity",
    "recrut", "recruit", "hiring", "inmail", "in-mail",
    "candidat", "candidate", "votre profil",
    "java", "developer", "developpeur", "engineer", "ingenieur",
    "freelance", "consultant", "cdi", "mission",
]

LINKEDIN_SOCIAL_NOISE_HINTS = [
    "a aime", "a partage", "a commente", "a reagi", "a publie", "a mentionne",
    "liked your", "shared", "commented", "reacted", "mentioned",
    "viewed your profile", "ont vu votre profil", "ont consulte", "a consulte",
    "voici les nouvelles", "actualites de votre reseau", "your network",
    "anniversaire", "felicit", "celebrate",
    "demande de connexion", "invitation a se connecter",
    "newsletter", "infolettre",
    "votre numero d'identification", "verification",
]


def _linkedin_subject_is_recruitment(subject_norm: str) -> bool:
    """Heuristic: a LinkedIn email is about recruitment iff the subject mentions
    an offer / role / position term and does NOT look like a social notification."""
    has_recruit_hint = any(h in subject_norm for h in LINKEDIN_RECRUITMENT_HINTS)
    has_social_hint = any(h in subject_norm for h in LINKEDIN_SOCIAL_NOISE_HINTS)
    return has_recruit_hint and not has_social_hint


def _find_matches(haystack: str, vocabulary: list[str]) -> list[str]:
    found: list[str] = []
    for kw in vocabulary:
        kw_norm = _normalize(kw)
        pattern = r"(?<![a-z0-9])" + re.escape(kw_norm) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            found.append(kw)
    return found


# Back-compat for older callers (mock extractor uses TECHNO_KEYWORDS, OK as-is).
# Keep alias so tests that imported JOB_INTENT_KEYWORDS still work — they don't
# in current code, but provide it just in case:
JOB_INTENT_KEYWORDS = STRONG_INTENT_KEYWORDS + WEAK_INTENT_KEYWORDS
