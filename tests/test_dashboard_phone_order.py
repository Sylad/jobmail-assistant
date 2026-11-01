"""L16 — tableau de bord : le document suit l'ordre du téléphone (liste des offres avant les
panneaux Pont Thunderbird et Analyse Ollama : WCAG 1.3.2 / 2.4.3) ; au bureau (≥ 769 px) le CSS
remonte les panneaux au-dessus des filtres. Les mesures en navigateur (390 et 1440 px) sont dans
le rapport de lot ; ici, la structure et les règles qui les produisent."""
from __future__ import annotations

import re

from tests.test_dashboard_web import CSS, _client


def _block(media: str) -> str:
    m = re.search(r"@media \(" + re.escape(media) + r"\) \{(.*?)\n\}\n", CSS, re.S)
    assert m, f"bloc @media ({media}) absent"
    return m.group(1)


def _stack(html: str) -> str:
    m = re.search(r'<div class="dashboard-stack">(.*)', html, re.S)
    assert m, "conteneur .dashboard-stack absent"
    return m.group(1)


def test_le_document_met_la_liste_des_offres_avant_les_panneaux(tmp_path):
    stack = _stack(_client(tmp_path, [(9, "new")]).get("/").text)
    marqueurs = ["page-header", "kpi-grid", 'class="filters"', "offers-wrap",
                 "Pont Thunderbird", "Analyse Ollama"]
    positions = [stack.find(x) for x in marqueurs]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions), positions


def test_a_390_px_un_ecart_de_20_px_separe_la_liste_du_premier_panneau():
    css = _block("max-width: 768px")
    assert re.search(r"\.offers-wrap\s*\{[^}]*margin-bottom:\s*20px", css)
    # le téléphone ne réordonne rien : plus de `order` dans ce bloc
    assert "order:" not in css


def test_a_1440_px_les_panneaux_restent_au_dessus_des_filtres_et_de_la_liste():
    css = _block("min-width: 769px")
    assert re.search(r"\.dashboard-stack\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column", css)
    p = re.search(r"\.dashboard-stack\s*>\s*\.reanalysis-panel\s*\{[^}]*order:\s*(\d+)", css)
    f = re.search(r"\.dashboard-stack\s*>\s*\.filters,\s*\.dashboard-stack\s*>\s*\.offers-wrap\s*\{[^}]*order:\s*(\d+)", css)
    assert p and f and 0 < int(p.group(1)) < int(f.group(1))
