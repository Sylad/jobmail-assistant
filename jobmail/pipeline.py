from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .config import Settings, get_settings
from .db import connect, email_exists, init_db, insert_email, upsert_offer
from .extraction import get_extractor
from .extraction.base import ExtractorProvider
from .filtering.rules import classify
from .mail.imap_client import fetch_recent
from .models import RawEmail

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineStats:
    fetched: int = 0
    new: int = 0
    job_related: int = 0
    extracted: int = 0
    skipped_non_job: int = 0
    sent_to_llm: int = 0


def run(source: Iterable[RawEmail] | None = None, *, settings: Settings | None = None) -> PipelineStats:
    """Fetch → local filter → extract (job-related only) → store.

    PRIVACY INVARIANT: emails with is_job_related=False are NEVER passed to
    the extractor. The filter runs 100% locally on the user's machine."""
    settings = settings or get_settings()
    init_db(settings.db_path)
    extractor = get_extractor(settings)

    emails = source if source is not None else fetch_recent(settings)
    stats = PipelineStats()

    with connect(settings.db_path) as conn:
        for email in emails:
            stats.fetched += 1
            if email_exists(conn, email.uid):
                continue
            stats.new += 1

            result = classify(email.subject, email.body_text)
            insert_email(
                conn, email,
                job_related=result.is_job_related,
                matched_keywords=result.all_matches,
            )

            if not result.is_job_related:
                stats.skipped_non_job += 1
                logger.debug("Skipped non-job mail uid=%s subj=%r", email.uid, email.subject)
                continue

            stats.job_related += 1
            stats.sent_to_llm += 1
            extraction = _safe_extract(extractor, email, settings.target_profile)
            upsert_offer(conn, email.uid, extraction)
            stats.extracted += 1

    return stats


def _safe_extract(extractor: ExtractorProvider, email: RawEmail, profile: str):
    try:
        return extractor.extract(email, profile)
    except Exception:
        logger.exception("Extractor failed on uid=%s", email.uid)
        from .models import OfferExtraction
        return OfferExtraction()
