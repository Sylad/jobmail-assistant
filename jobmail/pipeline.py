from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .config import Settings, get_settings
from .db import connect, email_exists, init_db, insert_email, upsert_offer
from .extraction import get_extractor
from .extraction.base import ExtractorProvider, PrivacyError
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
    dry_run: bool = False


def run(
    source: Iterable[RawEmail] | None = None,
    *,
    settings: Settings | None = None,
    dry_run: bool | None = None,
) -> PipelineStats:
    """Fetch → local filter → extract (job-related only) → store.

    PRIVACY INVARIANT: emails with is_job_related=False are NEVER passed to
    the extractor. The filter runs 100% locally on the user's machine."""
    settings = settings or get_settings()
    dry_run = settings.dry_run if dry_run is None else dry_run
    init_db(settings.db_path)
    extractor: ExtractorProvider | None = None

    emails = source if source is not None else fetch_recent(settings)
    stats = PipelineStats(dry_run=dry_run)
    logger.info("Pipeline started provider=%s dry_run=%s", settings.llm_provider, dry_run)

    # One transaction per email so progress is visible in real time and a
    # crash mid-run doesn't lose the work done so far.
    for email in emails:
        stats.fetched += 1
        with connect(settings.db_path) as conn:
            if email_exists(conn, email.uid):
                continue
            stats.new += 1

            result = classify(email.subject, email.body_text, sender=email.sender)
            insert_email(
                conn, email,
                job_related=result.is_job_related,
                matched_keywords=result.all_matches,
            )

            if not result.is_job_related:
                stats.skipped_non_job += 1
                logger.debug("Skipped non-job mail uid=%s matched=%d", email.uid, len(result.all_matches))
                continue

            stats.job_related += 1
            if dry_run:
                logger.info("Dry-run kept job-related mail uid=%s matched=%d", email.uid, len(result.all_matches))
                continue

            if extractor is None:
                extractor = get_extractor(settings)

            stats.sent_to_llm += 1
            extraction = _safe_extract(extractor, email, settings.target_profile)
            upsert_offer(conn, email.uid, extraction)
            stats.extracted += 1
            logger.info(
                "Extracted uid=%s score=%d company=%r",
                email.uid, extraction.relevance_score, extraction.company[:30],
            )

    return stats


def _safe_extract(extractor: ExtractorProvider, email: RawEmail, profile: str):
    try:
        return extractor.extract(email, profile)
    except PrivacyError:
        logger.exception("Privacy guard blocked extraction uid=%s", email.uid)
        raise
    except Exception:
        logger.exception("Extractor failed on uid=%s", email.uid)
        from .models import OfferExtraction
        return OfferExtraction()
