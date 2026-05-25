from __future__ import annotations

import json
import logging

import httpx

from ..config import Settings
from ..models import ContractType, OfferExtraction, RawEmail, WorkMode
from .base import ExtractorProvider

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Tu es un assistant qui extrait les infos structurées d'un mail
de recrutement. Réponds UNIQUEMENT par un objet JSON valide, sans markdown,
sans texte autour.

Schéma attendu:
{{
  "title": "string",
  "company": "string",
  "recruiter": "string",
  "location": "string",
  "work_mode": "remote|hybrid|onsite|unknown",
  "technos": ["string"],
  "english_required": true|false,
  "contract_type": "cdi|cdd|freelance|mission|unknown",
  "summary": "string (<= 400 chars)",
  "relevance_score": 0-10
}}

Profil ciblé pour le scoring: {profile}

De: {sender}
Sujet: {subject}
---
{body}
"""


class OllamaExtractor(ExtractorProvider):
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        prompt = PROMPT_TEMPLATE.format(
            profile=target_profile,
            sender=email.sender,
            subject=email.subject,
            body=email.body_text[:4000],
        )
        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            payload = json.loads(data.get("response", "{}"))
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("Ollama extraction failed: %s", e)
            return OfferExtraction()

        return OfferExtraction(
            title=payload.get("title", ""),
            company=payload.get("company", ""),
            recruiter=payload.get("recruiter", ""),
            location=payload.get("location", ""),
            work_mode=_safe_enum(WorkMode, payload.get("work_mode")),
            technos=list(payload.get("technos", [])),
            english_required=bool(payload.get("english_required", False)),
            contract_type=_safe_enum(ContractType, payload.get("contract_type")),
            summary=payload.get("summary", ""),
            relevance_score=int(payload.get("relevance_score", 0) or 0),
        )


def _safe_enum(enum_cls, value):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return enum_cls("unknown")
