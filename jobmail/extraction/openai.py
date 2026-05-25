from __future__ import annotations

from ..config import Settings
from ..models import OfferExtraction, RawEmail
from .base import ExtractorProvider


class OpenAIExtractor(ExtractorProvider):
    """Stub. Plug `openai` SDK with structured outputs (response_format=json_schema).

    Keep schema identical to Claude's tool input — see `extraction.claude.TOOL_SCHEMA`.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        raise NotImplementedError(
            "OpenAI provider is a stub. Implement with openai>=1.55 "
            "client.chat.completions.create(response_format={'type':'json_schema',...})."
        )
