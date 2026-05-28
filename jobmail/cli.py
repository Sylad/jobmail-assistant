from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import uvicorn

from .config import get_settings
from .mail.sources import build_mbox_source
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
    link_parser = sub.add_parser(
        "link-offers",
        help="Fill offer_url from cached mail links without calling the LLM.",
    )
    link_parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Process at most N offers.",
    )
    watch_parser = sub.add_parser(
        "watch",
        help="Watch MBOX file(s) for changes and trigger incremental fetch on each new mail.",
    )
    watch_parser.add_argument(
        "--mbox", action="append", default=[], required=True, metavar="PATH",
        help="MBOX path to watch. Repeatable.",
    )
    watch_parser.add_argument(
        "--interval", type=float, default=30.0, metavar="SECONDS",
        help="Polling interval in seconds (default 30; inotify is unreliable on /mnt/c).",
    )
    watch_parser.add_argument(
        "--since-days", type=int, default=None, metavar="N",
        help="On first scan, only ingest mails newer than N days.",
    )

    extract_parser = sub.add_parser(
        "extract",
        help="Run LLM extraction on cached job-related mails that have no offer yet.",
    )
    extract_parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Process at most N mails (useful for sampling before a big run).",
    )
    extract_parser.add_argument(
        "--re-extract", action="store_true",
        help="Also re-extract offers that already exist (useful after a prompt tweak).",
    )

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
        source = build_mbox_source(mbox_paths, since_days, settings=settings) if mbox_paths else None
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

    if args.cmd == "watch":
        return _run_watch(
            settings,
            paths=args.mbox,
            interval=args.interval,
            since_days=args.since_days,
        )

    if args.cmd == "extract":
        return _run_extract(settings, limit=args.limit, re_extract=args.re_extract)

    if args.cmd == "link-offers":
        return _run_link_offers(settings, limit=args.limit)

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


def _run_watch(
    settings,
    *,
    paths: list[str],
    interval: float,
    since_days: int | None,
) -> int:
    """Long-running poll loop: on each MBOX size+mtime change, trigger an
    incremental fetch on just that path. Uses polling (stat-based) which is
    reliable across the WSL2 9p boundary where inotify isn't.

    Quick stat checks every `interval` seconds — negligible CPU. The actual
    parse + LLM extraction only fires when a file changed.
    """
    import signal
    import time

    from .pipeline import run as run_pipeline

    abs_paths = [str(Path(p).expanduser().resolve()) for p in paths]
    for p in abs_paths:
        if not Path(p).is_file():
            logging.error("MBOX not found, ignoring: %s", p)
    abs_paths = [p for p in abs_paths if Path(p).is_file()]
    if not abs_paths:
        logging.error("No valid MBOX paths to watch.")
        return 1

    # Seed last signatures from current state — we don't want to re-process
    # everything on startup. Use stat snapshot as baseline; a real first-time
    # run should use `jobmail fetch` separately.
    signatures: dict[str, tuple[int, float]] = {}
    for p in abs_paths:
        stat = Path(p).stat()
        signatures[p] = (stat.st_size, stat.st_mtime)
        logging.info("Watching %s (%.1f MB)", Path(p).name, stat.st_size / 1024 / 1024)

    stopping = False

    def _on_sigint(_sig, _frame):
        nonlocal stopping
        stopping = True
        logging.info("Shutdown requested — finishing current cycle then exiting.")

    signal.signal(signal.SIGINT, _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigint)

    logging.info("Watch loop started: %d paths, interval=%.0fs. Ctrl+C to stop.",
                 len(abs_paths), interval)

    while not stopping:
        time.sleep(interval)
        for p in abs_paths:
            try:
                stat = Path(p).stat()
            except FileNotFoundError:
                logging.warning("MBOX disappeared: %s", p)
                continue
            sig = (stat.st_size, stat.st_mtime)
            if sig == signatures[p]:
                continue

            old_size, _ = signatures[p]
            delta = stat.st_size - old_size
            logging.info("MBOX changed: %s (+%d bytes) — fetching…",
                         Path(p).name, delta)

            source = build_mbox_source([p], since_days=since_days, settings=settings)
            try:
                stats = run_pipeline(source=source, settings=settings)
            except Exception:
                logging.exception("Fetch failed for %s", p)
                continue

            logging.info(
                "Fetch result: new=%d, job=%d, llm=%d",
                stats.new, stats.job_related, stats.sent_to_llm,
            )
            signatures[p] = sig

    logging.info("Watch loop exited.")
    return 0


def _run_extract(settings, *, limit: int | None, re_extract: bool) -> int:
    """Run LLM extraction on emails already in the DB. Bypasses fetch+classify
    and is intended for two flows:
      - first-time extraction of mails that were ingested earlier (e.g. left
        over from a partial run);
      - re-extraction of all offers after a prompt tweak (--re-extract).
    """
    from datetime import datetime

    from .db import connect, upsert_offer
    from .extraction import get_extractor
    from .extraction.base import PrivacyError
    from .models import RawEmail

    if not _provider_available(settings):
        print(
            f"LLM provider {settings.llm_provider!r} is not reachable. "
            "Aborting before touching existing offers."
        )
        return 2

    extractor = get_extractor(settings)
    sql = """
        SELECT e.uid, e.message_id, e.subject, e.sender, e.received_at, e.body_text, e.body_html
        FROM emails e
        WHERE e.job_related = 1
        {join}
        ORDER BY e.received_at DESC
        {limit}
    """.format(
        join="" if re_extract else "AND e.uid NOT IN (SELECT email_uid FROM offers)",
        limit=f"LIMIT {int(limit)}" if limit else "",
    )

    with connect(settings.db_path) as conn:
        rows = conn.execute(sql).fetchall()

    if not rows:
        print("Nothing to extract — no job_related mails without offers in DB.")
        return 0

    print(f"Extracting {len(rows)} mail(s) via {settings.llm_provider}…")
    done = 0
    failed = 0
    for row in rows:
        email = RawEmail(
            uid=row["uid"],
            message_id=row["message_id"],
            subject=row["subject"],
            sender=row["sender"],
            received_at=datetime.fromisoformat(row["received_at"]),
            body_text=row["body_text"],
            body_html=row["body_html"] or "",
        )
        try:
            extraction = extractor.extract(email, settings.target_profile)
        except PrivacyError:
            logging.warning("Privacy guard refused email uid=%s — skipping.", email.uid)
            failed += 1
            continue
        except Exception:
            logging.exception("Extraction failed uid=%s", email.uid)
            failed += 1
            continue
        if _empty_extraction(extraction):
            logging.warning("Empty extraction uid=%s — preserving existing offer.", email.uid)
            failed += 1
            continue
        with connect(settings.db_path) as conn:
            upsert_offer(conn, email.uid, extraction)
        done += 1
        if done % 5 == 0:
            print(f"  {done}/{len(rows)}")
    print(f"Done. extracted={done} failed={failed}")
    return 0


def _run_link_offers(settings, *, limit: int | None) -> int:
    from .db import connect
    from .web.links import build_preferred_offer_terms, extract_offer_links

    sql = """
        SELECT
            o.id, o.title, o.company, e.subject, e.body_text, e.body_html
        FROM offers o
        JOIN emails e ON e.uid = o.email_uid
        ORDER BY e.received_at DESC
        {limit}
    """.format(limit=f"LIMIT {int(limit)}" if limit else "")

    with connect(settings.db_path) as conn:
        rows = conn.execute(sql).fetchall()

    processed = 0
    updated = 0
    missing = 0
    for row in rows:
        links = extract_offer_links(
            row["body_text"] or "",
            row["body_html"] or "",
            preferred_terms=build_preferred_offer_terms(
                row["title"] or "",
                row["company"] or "",
                row["subject"] or "",
            ),
            max_links=1,
        )
        processed += 1
        if not links:
            missing += 1
            continue
        with connect(settings.db_path) as conn:
            conn.execute(
                "UPDATE offers SET offer_url = ?, extracted_at = datetime('now') WHERE id = ?",
                (links[0].url, row["id"]),
            )
        updated += 1
        if processed % 50 == 0:
            print(f"  {processed}/{len(rows)} updated={updated} missing={missing}")

    print(f"Done. processed={processed} updated={updated} missing={missing}")
    return 0


def _provider_available(settings) -> bool:
    if settings.llm_provider != "ollama":
        return True
    import httpx

    try:
        resp = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=2)
        resp.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def _empty_extraction(extraction) -> bool:
    return (
        not extraction.title
        and not extraction.company
        and not extraction.recruiter
        and not extraction.location
        and not extraction.technos
        and not extraction.summary
        and not extraction.offer_url
        and extraction.relevance_score == 0
    )


def _build_mbox_source(
    paths: list[str],
    since_days: int | None = None,
    *,
    settings=None,
):
    return build_mbox_source(paths, since_days, settings=settings)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
