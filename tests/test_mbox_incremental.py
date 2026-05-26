"""Incremental MBOX reader — second run yields only the newly appended mails."""
from __future__ import annotations

from pathlib import Path

from jobmail.db import connect, get_mbox_state, init_db
from jobmail.mail.mbox_reader import iter_with_offsets
from jobmail.mail.thunderbird import read_mbox
from jobmail.pipeline import run as run_pipeline


def _make_msg(idx: int, day: int) -> str:
    """Build a single MBOX entry, dated 2026-01-DD."""
    return (
        f"From sender{idx}@example.com Mon Jan {day:02d} 12:00:00 2026\n"
        f"Date: Mon, {day:02d} Jan 2026 12:00:00 +0000\n"
        f"From: sender{idx}@example.com\n"
        f"To: me@example.com\n"
        f"Subject: Synthetic mail {idx}\n"
        f"Message-Id: <synth-{idx}@local>\n"
        f"Content-Type: text/plain; charset=us-ascii\n"
        f"\n"
        f"Body of mail {idx}\n"
        f"\n"
    )


def _write_mbox(path: Path, count: int, start: int = 1) -> None:
    body = "".join(_make_msg(start + i, day=(start + i) % 28 + 1) for i in range(count))
    path.write_text(body, encoding="utf-8")


def _append_mbox(path: Path, count: int, start: int) -> None:
    existing = path.read_text(encoding="utf-8")
    new = "".join(_make_msg(start + i, day=(start + i) % 28 + 1) for i in range(count))
    path.write_text(existing + new, encoding="utf-8")


def test_iter_with_offsets_yields_each_message(tmp_path: Path):
    mbox = tmp_path / "test.mbox"
    _write_mbox(mbox, 4)

    results = list(iter_with_offsets(mbox))
    assert len(results) == 4
    offsets = [off for off, _ in results]
    # Offsets must be strictly increasing
    assert offsets == sorted(offsets)
    # First offset is 0
    assert offsets[0] == 0


def test_resume_from_offset_skips_already_consumed(tmp_path: Path):
    mbox = tmp_path / "test.mbox"
    _write_mbox(mbox, 4)

    full = list(iter_with_offsets(mbox))
    second_offset = full[1][0]

    # Resume mid-file: should only see msg #1 onward (the one AT that offset)
    resumed = list(iter_with_offsets(mbox, start_offset=second_offset))
    assert len(resumed) == 3
    assert resumed[0][1].get("Subject") == "Synthetic mail 2"


def test_pipeline_first_run_then_append(tmp_path: Path, monkeypatch):
    from jobmail.config import Settings

    settings = Settings(
        db_path=tmp_path / "test.db",
        llm_provider="mock",
        imap_host="",
        target_profile="generic",
    )
    mbox = tmp_path / "test.mbox"
    _write_mbox(mbox, 3)

    # Stream constructor for our test: just read_mbox directly with state lookup.
    init_db(settings.db_path)

    def _source_with_state():
        from jobmail.db import connect, get_mbox_state
        with connect(settings.db_path) as conn:
            state = get_mbox_state(conn, str(mbox))
        offset = state["last_offset"] if state else 0
        yield from read_mbox(mbox, start_offset=offset)

    stats1 = run_pipeline(source=_source_with_state(), settings=settings)
    assert stats1.fetched == 3
    assert stats1.new == 3

    # Verify state was persisted on the last message
    with connect(settings.db_path) as conn:
        state = get_mbox_state(conn, str(mbox))
    assert state is not None
    assert state["last_offset"] > 0
    last_offset_after_first = state["last_offset"]

    # Append 2 new mails
    _append_mbox(mbox, 2, start=4)

    stats2 = run_pipeline(source=_source_with_state(), settings=settings)
    # Resume jumps over the consumed mails — the reader yields starting from the
    # last known offset (i.e. the LAST consumed mail re-yielded as boundary, plus
    # the 2 new ones)
    assert stats2.new == 2, f"expected 2 new mails, got {stats2.new}"

    with connect(settings.db_path) as conn:
        state = get_mbox_state(conn, str(mbox))
    assert state["last_offset"] > last_offset_after_first


def test_compact_detection_shrunk_file_resets_to_zero(tmp_path: Path):
    """When a MBOX shrinks (Thunderbird Compact Folders), the resume cursor
    must NOT be trusted — we need a full re-scan."""
    from jobmail.db import update_mbox_state

    db_path = tmp_path / "test.db"
    mbox = tmp_path / "test.mbox"
    _write_mbox(mbox, 5)
    init_db(db_path)

    # Pretend the state says the file was big (10000 bytes); now it's smaller.
    with connect(db_path) as conn:
        update_mbox_state(
            conn, str(mbox.resolve()),
            last_offset=8000,
            last_size=10000,
            last_mtime=mbox.stat().st_mtime,
        )

    from jobmail.cli import _build_mbox_source
    from jobmail.config import Settings

    settings = Settings(db_path=db_path, llm_provider="mock", imap_host="")
    source = _build_mbox_source([str(mbox)], settings=settings)
    mails = list(source)
    # Should have re-read everything from offset 0 → all 5 mails.
    assert len(mails) == 5
