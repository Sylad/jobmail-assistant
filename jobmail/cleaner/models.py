from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class CleanerCandidate:
    uid: str
    received_at: datetime
    sender: str
    subject: str
    reason: str
    source: str = "imap"
    mailbox: str = ""
    source_path: str = ""

    @property
    def can_move(self) -> bool:
        return self.source in {"imap", "mbox"}


@dataclass(slots=True)
class CleanerReport:
    scanned_count: int = 0
    candidates: list[CleanerCandidate] = field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def top_senders(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for candidate in self.candidates:
            sender = candidate.sender.strip() or "(expediteur inconnu)"
            counts[sender] = counts.get(sender, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:10]
