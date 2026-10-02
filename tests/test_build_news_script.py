"""scripts/build-news.sh : le dossier compilé versionné n'est remplacé qu'en cas de succès."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _layout(tmp_path: Path, cadence_body: str) -> tuple[Path, Path, dict]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "build-news.sh", root / "scripts" / "build-news.sh")
    out = root / "jobmail" / "web" / "static" / "nouveautes-data"
    out.mkdir(parents=True)
    (out / "nouveautes.json").write_text("ANCIEN", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "cadence"
    fake.write_text("#!/usr/bin/env bash\n" + cadence_body, encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}
    return root, out, env


def test_failed_build_keeps_the_committed_folder(tmp_path):
    root, out, env = _layout(tmp_path, "echo 'entrée illisible' >&2\nexit 1\n")
    res = subprocess.run(["bash", "scripts/build-news.sh"], cwd=root, env=env, capture_output=True)
    assert res.returncode != 0
    assert (out / "nouveautes.json").read_text(encoding="utf-8") == "ANCIEN"
    assert sorted(p.name for p in out.parent.iterdir()) == ["nouveautes-data"]


def test_missing_cadence_keeps_the_committed_folder(tmp_path):
    root, out, env = _layout(tmp_path, "exit 0\n")
    (tmp_path / "bin" / "cadence").unlink()
    res = subprocess.run(["bash", "scripts/build-news.sh"], cwd=root, env=env, capture_output=True)
    assert res.returncode != 0
    assert (out / "nouveautes.json").read_text(encoding="utf-8") == "ANCIEN"


def test_successful_build_replaces_the_folder_without_index_page(tmp_path):
    body = (
        'while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done\n'
        'mkdir -p "$out/captures"; echo NOUVEAU > "$out/nouveautes.json"\n'
        'echo page > "$out/index.html"; echo png > "$out/captures/a.png"\n'
    )
    root, out, env = _layout(tmp_path, body)
    res = subprocess.run(["bash", "scripts/build-news.sh"], cwd=root, env=env, capture_output=True)
    assert res.returncode == 0, res.stderr
    assert (out / "nouveautes.json").read_text(encoding="utf-8").strip() == "NOUVEAU"
    assert (out / "captures" / "a.png").exists()
    assert not (out / "index.html").exists()
    assert sorted(p.name for p in out.parent.iterdir()) == ["nouveautes-data"]
