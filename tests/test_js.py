"""Lance les tests JavaScript du client (node --test tests/js/) depuis pytest quand Node
est installé : la suite complète reste `pytest`."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_node_suite_passes():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node absent : tests JavaScript non lancés (node --test tests/js/)")
    result = subprocess.run(
        [node, "--test", "tests/js/"], cwd=REPO, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
