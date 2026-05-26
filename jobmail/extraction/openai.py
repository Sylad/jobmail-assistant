from __future__ import annotations

import json
import logging

from ..config import Settings
from ..models import ContractType, OfferExtraction, RawEmail, WorkMode
from .base import CloudLLMProvider
from .claude import TOOL_SCHEMA, build_payload

logger = logging.getLogger(__name__)


class OpenAIProvider(CloudLLMProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY missing in .env")
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "openai SDK not installed. Run: pip install 'jobmail-assistant[openai]'"
            ) from e
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def _extract_job_related(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        resp = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract structured job-offer data. Return only valid JSON "
                        "matching the record_offer schema."
                    ),
                },
                {"role": "user", "content": build_payload(email, target_profile)},
            ],
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("OpenAI returned invalid JSON; falling back to empty extraction.")
            return OfferExtraction()
        return _from_json(data)


def _from_json(data: dict) -> OfferExtraction:
    return OfferExtraction(
        title=str(data.get("title", "") or ""),
        company=str(data.get("company", "") or ""),
        recruiter=str(data.get("recruiter", "") or ""),
        location=str(data.get("location", "") or ""),
        work_mode=_safe_enum(WorkMode, data.get("work_mode")),
        technos=[str(t).strip().lower() for t in data.get("technos", []) if str(t).strip()],
        english_required=bool(data.get("english_required", False)),
        contract_type=_safe_enum(ContractType, data.get("contract_type")),
        summary=str(data.get("summary", "") or "")[:400],
        relevance_score=_safe_score(data.get("relevance_score", 0)),
    )


def _safe_score(value) -> int:
    try:
        score = int(value or 0)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(10, score))


def _safe_enum(enum_cls, value):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return enum_cls("unknown")


OPENAI_JSON_SCHEMA = TOOL_SCHEMA["input_schema"]
OpenAIExtractor = OpenAIProvider
