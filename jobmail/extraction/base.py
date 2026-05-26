from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings
from ..filtering.rules import classify
from ..models import OfferExtraction, RawEmail
from ..privacy import anonymize_email


class PrivacyError(RuntimeError):
    """Raised when a cloud provider is asked to process a non-job email."""


class LLMProvider(ABC):
    """Single-method interface. Implementations MUST be idempotent and
    MUST NOT leak the raw email to anywhere outside their own call site."""

    is_cloud: bool = False

    @abstractmethod
    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        ...


class LocalLLMProvider(LLMProvider):
    """Base class for providers that stay on the user's machine."""


class CloudLLMProvider(LLMProvider):
    """Cloud providers get a second local privacy gate and anonymized payloads."""

    is_cloud = True

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        local_result = classify(email.subject, email.body_text, sender=email.sender)
        if not local_result.is_job_related:
            raise PrivacyError("Refusing cloud extraction for non-job email.")
        return self._extract_job_related(anonymize_email(email), target_profile)

    @abstractmethod
    def _extract_job_related(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        ...


ExtractorProvider = LLMProvider


def get_extractor(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    if provider == "mock":
        from .mock import MockProvider
        return MockProvider()
    if provider == "claude":
        from .claude import ClaudeProvider
        return ClaudeProvider(settings)
    if provider == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(settings)
    if provider == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(settings)
    raise ValueError(f"Unknown LLM_PROVIDER={provider!r}")
