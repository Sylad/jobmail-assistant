from __future__ import annotations

import json
import logging

from ..config import Settings
from ..models import ContractType, OfferExtraction, RawEmail, WorkMode
from .base import ExtractorProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un assistant qui extrait des informations structurées
d'un mail de recrutement. Tu ne reçois que des mails déjà filtrés comme étant
liés à l'emploi. Réponds UNIQUEMENT via l'outil `record_offer`. Si une info
n'est pas dans le mail, laisse une chaîne vide ou la valeur 'unknown'."""

TOOL_SCHEMA = {
    "name": "record_offer",
    "description": "Enregistre les détails structurés d'une offre d'emploi.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "company": {"type": "string"},
            "recruiter": {"type": "string"},
            "location": {"type": "string"},
            "work_mode": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unknown"]},
            "technos": {"type": "array", "items": {"type": "string"}},
            "english_required": {"type": "boolean"},
            "contract_type": {
                "type": "string",
                "enum": ["cdi", "cdd", "freelance", "mission", "unknown"],
            },
            "summary": {"type": "string", "maxLength": 400},
            "relevance_score": {
                "type": "integer", "minimum": 0, "maximum": 10,
                "description": "Pertinence pour le profil cible, 0 = hors-sujet, 10 = match parfait.",
            },
        },
        "required": [
            "title", "company", "work_mode", "technos",
            "contract_type", "summary", "relevance_score",
        ],
    },
}


class ClaudeExtractor(ExtractorProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing in .env")
        try:
            from anthropic import Anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK not installed. Run: pip install 'jobmail-assistant[claude]'"
            ) from e
        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        user_msg = _build_user_message(email, target_profile)
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_offer"},
            messages=[{"role": "user", "content": user_msg}],
        )

        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_offer":
                return _from_tool_input(block.input)

        logger.warning("Claude did not return record_offer tool call; falling back to empty.")
        return OfferExtraction()


def _build_user_message(email: RawEmail, target_profile: str) -> str:
    # Keep payload minimal: subject + first 4kB of normalized text + profile.
    snippet = email.body_text[:4000]
    return (
        f"Profil ciblé pour le scoring: {target_profile}\n"
        f"---\n"
        f"De: {email.sender}\n"
        f"Sujet: {email.subject}\n"
        f"---\n"
        f"{snippet}"
    )


def _from_tool_input(data: dict) -> OfferExtraction:
    return OfferExtraction(
        title=data.get("title", ""),
        company=data.get("company", ""),
        recruiter=data.get("recruiter", ""),
        location=data.get("location", ""),
        work_mode=WorkMode(data.get("work_mode", "unknown")),
        technos=list(data.get("technos", [])),
        english_required=bool(data.get("english_required", False)),
        contract_type=ContractType(data.get("contract_type", "unknown")),
        summary=data.get("summary", ""),
        relevance_score=int(data.get("relevance_score", 0)),
    )


# Used by tests to assert payload shape without hitting the SDK.
def build_payload(email: RawEmail, target_profile: str) -> str:
    return _build_user_message(email, target_profile)
