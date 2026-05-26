from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import uvicorn

from .config import get_settings
from .pipeline import run as run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobmail", description="JobMail Assistant — privacy-first.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    fetch_parser = sub.add_parser("fetch", help="Fetch IMAP or MBOX, filter, extract job offers.")
    fetch_parser.add_argument("--dry-run", action="store_true", help="Classify locally without LLM calls.")
    fetch_parser.add_argument(
        "--mbox", action="append", default=[], metavar="PATH",
        help="Read mails from a Thunderbird MBOX file instead of IMAP. Repeatable.",
    )
    fetch_parser.add_argument(
        "--since-days", type=int, default=None, metavar="N",
        help="Only mails received within the last N days.",
    )
    dry_run_parser = sub.add_parser("dry-run", help="Fetch and classify locally without LLM calls.")
    dry_run_parser.add_argument(
        "--mbox", action="append", default=[], metavar="PATH",
        help="Read mails from a Thunderbird MBOX file instead of IMAP. Repeatable.",
    )
    dry_run_parser.add_argument(
        "--since-days", type=int, default=None, metavar="N",
        help="Only mails received within the last N days.",
    )
    sub.add_parser("serve", help="Run the local web dashboard.")
    sub.add_parser("seed", help="Seed the DB with mock offers for demo.")
    sub.add_parser("classify", help="Re-classify cached emails (no LLM call unless new).")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    settings = get_settings()

    if args.cmd in {"fetch", "dry-run"}:
        dry_run = args.cmd == "dry-run" or getattr(args, "dry_run", False)
        mbox_paths: list[str] = getattr(args, "mbox", []) or []
        since_days: int | None = getattr(args, "since_days", None)
        source = _build_mbox_source(mbox_paths, since_days, settings=settings) if mbox_paths else None
        stats = run_pipeline(source=source, settings=settings, dry_run=dry_run)
        print(f"Done. fetched={stats.fetched} new={stats.new} "
              f"job={stats.job_related} sent_to_llm={stats.sent_to_llm} dry_run={stats.dry_run}")
        return 0

    if args.cmd == "serve":
        uvicorn.run(
            "jobmail.web.app:app",
            host=settings.web_host,
            port=settings.web_port,
            reload=False,
        )
        return 0

    if args.cmd == "seed":
        from .seed import seed
        n = seed(settings)
        print(f"Seeded {n} mock offers. Open http://{settings.web_host}:{settings.web_port}/")
        return 0

    if args.cmd == "classify":
        # Lightweight re-classify on cached body — useful when rules.py changes.
        from .db import connect
        from .filtering.rules import classify
        with connect(settings.db_path) as conn:
            rows = conn.execute("SELECT uid, subject, sender, body_text FROM emails").fetchall()
            for r in rows:
                res = classify(r["subject"], r["body_text"], sender=r["sender"])
                conn.execute(
                    "UPDATE emails SET job_related = ?, matched_keywords = ? WHERE uid = ?",
                    (int(res.is_job_related), json.dumps(res.all_matches), r["uid"]),
                )
        print(f"Re-classified {len(rows)} cached emails.")
        return 0

    return 1


def _build_mbox_source(
    paths: list[str],
    since_days: int | None = None,
    *,
    settings=None,
):
    """Chain one or more MBOX files into a single email iterator with
    incremental resume.

    For each MBOX path we look up `mbox_state` in SQLite to know where the
    previous run stopped. If the file has grown, we seek to that offset and
    only yield the new tail. If the file has SHRUNK (Thunderbird Compact
    Folders), we reset to 0 and re-scan. The pipeline updates the cursor
    after each email is committed.
    """
    from datetime import datetime, timedelta, timezone

    from .config import get_settings
    from .db import connect, get_mbox_state, init_db
    from .mail.thunderbird import read_mbox
    from .models import RawEmail

    settings = settings or get_settings()
    init_db(settings.db_path)

    cutoff: datetime | None = None
    if since_days is not None and since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        logging.info("Filter: keep only mails newer than %s", cutoff.isoformat())

    def _stream():
        kept = 0
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            if not path.is_file():
                logging.error("MBOX path not found: %s", path)
                continue

            abs_path = str(path.resolve())
            stat = path.stat()
            current_size = stat.st_size
            current_mtime = stat.st_mtime

            # Decide resume offset.
            start_offset = 0
            with connect(settings.db_path) as conn:
                state = get_mbox_state(conn, abs_path)
            if state is not None:
                if current_size < state["last_size"]:
                    logging.warning(
                        "MBOX %s shrank (%d → %d bytes) — Thunderbird Compact suspected, "
                        "full re-scan from offset 0.",
                        path.name, state["last_size"], current_size,
                    )
                    start_offset = 0
                else:
                    start_offset = state["last_offset"]
                    logging.info(
                        "MBOX %s resume: offset=%d (file %d bytes, +%d new)",
                        path.name, start_offset, current_size,
                        current_size - state["last_size"],
                    )
            else:
                logging.info("MBOX %s: first scan (%d bytes)", path.name, current_size)

            tag = path.parent.name or path.stem
            for mail in read_mbox(path, since=cutoff, start_offset=start_offset):
                kept += 1
                if kept % 50 == 0:
                    logging.info("MBOX progress: %d mails yielded", kept)
                yield RawEmail(
                    uid=f"{tag}:mbox-{mail.mbox_offset}",
                    message_id=mail.message_id,
                    subject=mail.subject,
                    sender=mail.sender,
                    received_at=mail.received_at,
                    body_text=mail.body_text,
                    body_html=mail.body_html,
                    mbox_path=abs_path,
                    mbox_offset=mail.mbox_offset,
                )
        logging.info("MBOX done: %d mails kept", kept)

    return _stream()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
