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

CREATE TABLE IF NOT EXISTS mbox_state (
    path TEXT PRIMARY KEY,
    last_offset INTEGER NOT NULL DEFAULT 0,
    last_size INTEGER NOT NULL DEFAULT 0,
    last_mtime REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
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


def get_mbox_state(conn: sqlite3.Connection, path: str) -> dict | None:
    row = conn.execute(
        "SELECT last_offset, last_size, last_mtime FROM mbox_state WHERE path = ?",
        (path,),
    ).fetchone()
    if row is None:
        return None
    return {"last_offset": row["last_offset"], "last_size": row["last_size"], "last_mtime": row["last_mtime"]}


def update_mbox_state(
    conn: sqlite3.Connection,
    path: str,
    *,
    last_offset: int,
    last_size: int,
    last_mtime: float,
) -> None:
    conn.execute(
        """
        INSERT INTO mbox_state (path, last_offset, last_size, last_mtime, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
            last_offset = excluded.last_offset,
            last_size = excluded.last_size,
            last_mtime = excluded.last_mtime,
            updated_at = excluded.updated_at
        """,
        (path, last_offset, last_size, last_mtime),
    )


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
    sender_contains: str | None = None,
    since_days: int | None = None,
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
    if sender_contains:
        sql += " AND LOWER(e.sender) LIKE ?"
        params.append(f"%{sender_contains.lower()}%")
    if since_days is not None and since_days > 0:
        sql += " AND e.received_at >= datetime('now', ?)"
        params.append(f"-{int(since_days)} days")
    sql += " ORDER BY o.relevance_score DESC, e.received_at DESC"

    rows = conn.execute(sql, params).fetchall()
    offers = [_row_to_offer(r) for r in rows]
    if techno:
        techno_lc = techno.lower()
        offers = [o for o in offers if o.extraction and any(
            techno_lc in t.lower() for t in o.extraction.technos
        )]
    return offers


def all_sender_domains(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Sender domains across all offer-emails, with counts. Used to populate the
    dashboard's sender filter dropdown."""
    rows = conn.execute("""
        SELECT
          LOWER(SUBSTR(e.sender, INSTR(e.sender, '@') + 1)) AS domain,
          COUNT(*) AS n
        FROM offers o JOIN emails e ON e.uid = o.email_uid
        WHERE INSTR(e.sender, '@') > 0
        GROUP BY domain
        ORDER BY n DESC, domain ASC
    """).fetchall()
    # Strip trailing '>' (some senders are "Name <addr>" so the slice may keep it).
    out: list[tuple[str, int]] = []
    for r in rows:
        d = (r["domain"] or "").rstrip(">").strip()
        if d:
            out.append((d, r["n"]))
    return out


def get_offer(conn: sqlite3.Connection, offer_id: int, with_body: bool = False) -> StoredOffer | None:
    body_col = ", e.body_text" if with_body else ""
    row = conn.execute(
        f"""
        SELECT o.*, e.subject, e.sender, e.received_at{body_col}
        FROM offers o JOIN emails e ON e.uid = o.email_uid
        WHERE o.id = ?
        """,
        (offer_id,),
    ).fetchone()
    if row is None:
        return None
    offer = _row_to_offer(row)
    if with_body:
        offer.body_text = row["body_text"] or ""
    return offer


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
