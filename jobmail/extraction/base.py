from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings
from ..models import OfferExtraction, RawEmail


class ExtractorProvider(ABC):
    """Single-method interface. Implementations MUST be idempotent and
    MUST NOT leak the raw email to anywhere outside their own call site."""

    @abstractmethod
    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        ...


def get_extractor(settings: Settings) -> ExtractorProvider:
    provider = settings.llm_provider
    if provider == "mock":
        from .mock import MockExtractor
        return MockExtractor()
    if provider == "claude":
        from .claude import ClaudeExtractor
        return ClaudeExtractor(settings)
    if provider == "ollama":
        from .ollama import OllamaExtractor
        return OllamaExtractor(settings)
    if provider == "openai":
        from .openai import OpenAIExtractor
        return OpenAIExtractor(settings)
    raise ValueError(f"Unknown LLM_PROVIDER={provider!r}")
