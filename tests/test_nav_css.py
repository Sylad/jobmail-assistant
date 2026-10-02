"""Navigation (L6/L7) : garde-fous sur la feuille de style partagée. Le balayage des
largeurs 300 → 899 px se fait dans un navigateur (voir le rapport de lot) ; ici, les règles
qui l'ont fait échouer ne doivent pas revenir."""
from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "jobmail" / "web" / "static" / "style.css").read_text(
    encoding="utf-8"
)


def _rules(selector: str) -> list[str]:
    return re.findall(rf"(?:^|\}})\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.M)


def test_nav_labels_never_break_inside_a_word():
    for body in _rules(".nav-label"):
        assert "overflow-wrap" not in body and "word-break" not in body


def test_phone_badge_sits_on_the_corner_out_of_the_flow():
    bodies = _rules(".mobile-nav-item .news-badge")
    assert any("position: absolute" in b for b in bodies)
    assert any("position: relative" in b for b in _rules(".mobile-nav-item"))
