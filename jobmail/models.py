from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class ContractType(str, Enum):
    CDI = "cdi"
    CDD = "cdd"
    FREELANCE = "freelance"
    MISSION = "mission"
    UNKNOWN = "unknown"


class OfferStatus(str, Enum):
    NEW = "new"
    INTERESTING = "interesting"
    IGNORED = "ignored"
    REPLIED = "replied"


@dataclass(slots=True)
class RawEmail:
    """Local-only representation. NEVER sent in full to a cloud LLM."""

    uid: str
    message_id: str
    subject: str
    sender: str
    received_at: datetime
    body_text: str
    body_html: str = ""

    @property
    def fingerprint(self) -> str:
        """Stable id used for dedup; UID + Message-Id."""
        return f"{self.uid}::{self.message_id}"


@dataclass(slots=True)
class OfferExtraction:
    """LLM-extracted structured data. Produced only for job_related=True mails."""

    title: str = ""
    company: str = ""
    recruiter: str = ""
    location: str = ""
    work_mode: WorkMode = WorkMode.UNKNOWN
    technos: list[str] = field(default_factory=list)
    english_required: bool = False
    contract_type: ContractType = ContractType.UNKNOWN
    summary: str = ""
    relevance_score: int = 0  # 0..10


@dataclass(slots=True)
class StoredOffer:
    """Row from offers table joined with status."""

    id: int
    email_uid: str
    subject: str
    sender: str
    received_at: datetime
    job_related: bool
    extraction: OfferExtraction | None
    status: OfferStatus = OfferStatus.NEW
