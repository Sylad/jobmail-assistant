from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import (
    ContractType,
    OfferExtraction,
    OfferStatus,
    RawEmail,
    StoredOffer,
    WorkMode,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    uid TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    received_at TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT NOT NULL DEFAULT '',
    job_related INTEGER NOT NULL DEFAULT 0,
    matched_keywords TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid TEXT NOT NULL UNIQUE REFERENCES emails(uid) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    recruiter TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    work_mode TEXT NOT NULL DEFAULT 'unknown',
    technos TEXT NOT NULL DEFAULT '[]',
    english_required INTEGER NOT NULL DEFAULT 0,
    contract_type TEXT NOT NULL DEFAULT 'unknown',
    summary TEXT NOT NULL DEFAULT '',
    relevance_score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new',
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);
CREATE INDEX IF NOT EXISTS idx_offers_score ON offers(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_emails_job_related ON emails(job_related);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def email_exists(conn: sqlite3.Connection, uid: str) -> bool:
    row = conn.execute("SELECT 1 FROM emails WHERE uid = ?", (uid,)).fetchone()
    return row is not None


def insert_email(
    conn: sqlite3.Connection,
    email: RawEmail,
    *,
    job_related: bool,
    matched_keywords: list[str],
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO emails
            (uid, message_id, subject, sender, received_at, body_text, body_html,
             job_related, matched_keywords)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email.uid,
            email.message_id,
            email.subject,
            email.sender,
            email.received_at.isoformat(),
            email.body_text,
            email.body_html,
            int(job_related),
            json.dumps(matched_keywords, ensure_ascii=False),
        ),
    )


def upsert_offer(
    conn: sqlite3.Connection,
    email_uid: str,
    extraction: OfferExtraction,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO offers
            (email_uid, title, company, recruiter, location, work_mode, technos,
             english_required, contract_type, summary, relevance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email_uid) DO UPDATE SET
            title = excluded.title,
            company = excluded.company,
            recruiter = excluded.recruiter,
            location = excluded.location,
            work_mode = excluded.work_mode,
            technos = excluded.technos,
            english_required = excluded.english_required,
            contract_type = excluded.contract_type,
            summary = excluded.summary,
            relevance_score = excluded.relevance_score
        RETURNING id
        """,
        (
            email_uid,
            extraction.title,
            extraction.company,
            extraction.recruiter,
            extraction.location,
            extraction.work_mode.value,
            json.dumps(extraction.technos, ensure_ascii=False),
            int(extraction.english_required),
            extraction.contract_type.value,
            extraction.summary,
            extraction.relevance_score,
        ),
    )
    return cur.fetchone()[0]


def update_status(conn: sqlite3.Connection, offer_id: int, status: OfferStatus) -> None:
    conn.execute("UPDATE offers SET status = ? WHERE id = ?", (status.value, offer_id))


def list_offers(
    conn: sqlite3.Connection,
    *,
    status: OfferStatus | None = None,
    techno: str | None = None,
    min_score: int = 0,
) -> list[StoredOffer]:
    sql = """
    SELECT o.*, e.subject, e.sender, e.received_at
    FROM offers o
    JOIN emails e ON e.uid = o.email_uid
    WHERE o.relevance_score >= ?
    """
    params: list = [min_score]
    if status is not None:
        sql += " AND o.status = ?"
        params.append(status.value)
    sql += " ORDER BY o.relevance_score DESC, e.received_at DESC"

    rows = conn.execute(sql, params).fetchall()
    offers = [_row_to_offer(r) for r in rows]
    if techno:
        techno_lc = techno.lower()
        offers = [o for o in offers if o.extraction and any(
            techno_lc in t.lower() for t in o.extraction.technos
        )]
    return offers


def get_offer(conn: sqlite3.Connection, offer_id: int) -> StoredOffer | None:
    row = conn.execute(
        """
        SELECT o.*, e.subject, e.sender, e.received_at
        FROM offers o JOIN emails e ON e.uid = o.email_uid
        WHERE o.id = ?
        """,
        (offer_id,),
    ).fetchone()
    return _row_to_offer(row) if row else None


def all_known_technos(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT technos FROM offers").fetchall()
    technos: set[str] = set()
    for row in rows:
        technos.update(json.loads(row["technos"]))
    return sorted(technos, key=str.lower)


def _row_to_offer(row: sqlite3.Row) -> StoredOffer:
    extraction = OfferExtraction(
        title=row["title"],
        company=row["company"],
        recruiter=row["recruiter"],
        location=row["location"],
        work_mode=WorkMode(row["work_mode"]),
        technos=json.loads(row["technos"]),
        english_required=bool(row["english_required"]),
        contract_type=ContractType(row["contract_type"]),
        summary=row["summary"],
        relevance_score=row["relevance_score"],
    )
    return StoredOffer(
        id=row["id"],
        email_uid=row["email_uid"],
        subject=row["subject"],
        sender=row["sender"],
        received_at=datetime.fromisoformat(row["received_at"]),
        job_related=True,
        extraction=extraction,
        status=OfferStatus(row["status"]),
    )
