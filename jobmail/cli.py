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
        source = _build_mbox_source(mbox_paths, since_days) if mbox_paths else None
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


def _build_mbox_source(paths: list[str], since_days: int | None = None):
    """Chain one or more MBOX files into a single email iterator.

    UIDs are namespaced by the MBOX filename so duplicate indices across files
    don't collide. `since_days` filters out mails older than N days based on
    the parsed Date header (timezone-aware).
    """
    from datetime import datetime, timedelta, timezone

    from .mail.thunderbird import read_mbox
    from .models import RawEmail

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
            tag = path.parent.name or path.stem
            logging.info("Reading MBOX %s (since=%s)", path, cutoff.isoformat() if cutoff else "all")
            for mail in read_mbox(path, since=cutoff):
                kept += 1
                if kept % 50 == 0:
                    logging.info("MBOX progress: %d mails yielded", kept)
                yield RawEmail(
                    uid=f"{tag}:{mail.uid}",
                    message_id=mail.message_id,
                    subject=mail.subject,
                    sender=mail.sender,
                    received_at=mail.received_at,
                    body_text=mail.body_text,
                    body_html=mail.body_html,
                )
        logging.info("MBOX done: %d mails kept", kept)

    return _stream()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
