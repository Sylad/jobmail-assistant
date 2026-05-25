from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .config import get_settings
from .pipeline import run as run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobmail", description="JobMail Assistant — privacy-first.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="Fetch IMAP, filter, extract job offers.")
    sub.add_parser("serve", help="Run the local web dashboard.")
    sub.add_parser("seed", help="Seed the DB with mock offers for demo.")
    sub.add_parser("classify", help="Re-classify cached emails (no LLM call unless new).")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    settings = get_settings()

    if args.cmd == "fetch":
        stats = run_pipeline(settings=settings)
        print(f"Done. fetched={stats.fetched} new={stats.new} "
              f"job={stats.job_related} sent_to_llm={stats.sent_to_llm}")
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
            rows = conn.execute("SELECT uid, subject, body_text FROM emails").fetchall()
            for r in rows:
                res = classify(r["subject"], r["body_text"])
                conn.execute(
                    "UPDATE emails SET job_related = ? WHERE uid = ?",
                    (int(res.is_job_related), r["uid"]),
                )
        print(f"Re-classified {len(rows)} cached emails.")
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
