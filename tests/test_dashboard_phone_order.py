"""L16 — tableau de bord au téléphone (≤ 768 px) : la liste des offres passe au-dessus des
panneaux Pont Thunderbird et Analyse Ollama. L'ordre réel à 390 px est mesuré dans un navigateur
(voir le rapport de lot) ; ici, la structure et les règles qui le produisent."""
from __future__ import annotations

import re

from tests.test_dashboard_web import CSS, _client


def _media_768() -> str:
    m = re.search(r"@media \(max-width: 768px\) \{(.*?)\n\}\n", CSS, re.S)
    assert m, "bloc @media (max-width: 768px) absent"
    return m.group(1)


def _stack(html: str) -> str:
    m = re.search(r'<div class="dashboard-stack">(.*)</div>\s*</div>\s*</main>|'
                  r'<div class="dashboard-stack">(.*)', html, re.S)
    assert m, "conteneur .dashboard-stack absent"
    return m.group(1) or m.group(2)


def test_le_document_garde_l_ordre_du_bureau_dans_un_conteneur(tmp_path):
    html = _client(tmp_path, [(9, "new")]).get("/").text
    stack = _stack(html)
    # Ordre du document = ordre du bureau (inchangé) ; c'est le CSS ≤ 768 px qui le modifie.
    marqueurs = ["page-header", "kpi-grid", "Pont Thunderbird", "Analyse Ollama",
                 'class="filters"', "offers-wrap"]
    positions = [stack.find(x) for x in marqueurs]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions), positions


def test_a_390_px_les_panneaux_passent_apres_la_liste_des_offres():
    css = _media_768()
    assert re.search(r"\.dashboard-stack\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column", css)
    m = re.search(r"\.dashboard-stack\s*>\s*\.reanalysis-panel\s*\{[^}]*order:\s*(\d+)", css)
    assert m and int(m.group(1)) >= 1


def test_le_bureau_garde_l_ordre_du_document():
    hors_768 = CSS.replace(_media_768(), "")
    # aucune règle `order` sur le tableau de bord hors du bloc ≤ 768 px
    assert not re.search(r"\.dashboard-stack[^{]*\{[^}]*order:", hors_768)
    assert not re.search(r"\.dashboard-stack\s*\{[^}]*display:\s*flex", hors_768)
