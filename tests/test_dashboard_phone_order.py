"""L16 — tableau de bord : un seul ordre à toutes les largeurs, bureau compris. La liste des offres
précède les panneaux Pont Thunderbird et Analyse Ollama dans le document (WCAG 1.3.2 / 2.4.3) ET à
l'écran : aucun `order` ne réordonne les enfants de .dashboard-stack. Les mesures en navigateur
(390 et 1440 px) sont dans le rapport de lot ; ici, la structure et les règles."""
from __future__ import annotations

import re

from tests.test_dashboard_web import CSS, _client


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


def test_un_ecart_de_20_px_separe_la_liste_du_premier_panneau_a_toute_largeur():
    # règle hors de tout @media : valable à 390 comme à 1440 px
    hors_media = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", CSS)
    assert re.search(r"\.dashboard-stack\s*>\s*\.offers-wrap\s*\{[^}]*margin-bottom:\s*20px", hors_media)


def test_aucun_order_sur_les_enfants_de_dashboard_stack_a_aucune_largeur():
    for m in re.finditer(r"([^{}]*\.dashboard-stack[^{}]*)\{([^}]*)\}", CSS):
        assert "order" not in re.findall(r"([\w-]+)\s*:", m.group(2)), m.group(0)
    # et aucune règle `order` sur les trois blocs de la pile, où qu'elle soit
    for sel in ("filters", "offers-wrap", "reanalysis-panel"):
        for m in re.finditer(r"\." + sel + r"\s*\{([^}]*)\}", CSS):
            assert not re.search(r"(?<![\w-])order\s*:", m.group(1)), (sel, m.group(0))
