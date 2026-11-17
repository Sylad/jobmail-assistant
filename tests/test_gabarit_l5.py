"""Revue UX du gabarit commun (L5) : une règle par test, nommée « Rn — … »."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from jobmail.web import app as web_app

CSS = (Path(__file__).resolve().parents[1] / "jobmail" / "web" / "static" / "style.css").read_text(
    encoding="utf-8"
)


def _rules(selector: str) -> list[str]:
    return re.findall(rf"(?:^|\}})\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.M)


def _page(path: str) -> str:
    return TestClient(web_app.create_app()).get(path).text


def _reduced_motion_block() -> str:
    m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", CSS, re.S)
    assert m, "bloc prefers-reduced-motion absent"
    return m.group(1)


def test_R1_mouvement_reduit_coupe_pulsation_enfoncement_et_transitions():
    # WCAG 2.3.3 (L3/t2) : pulse-dot de .live-dot et translateY de .btn:active.
    block = _reduced_motion_block()
    assert re.search(r"\.live-dot \{ animation: none; \}", block)
    assert re.search(r"\.btn:active \{ transform: none; \}", block)
    assert "transition-duration: 0.01ms !important" in block
    assert "animation-duration: 0.01ms !important" in block


def test_R2_textes_du_bas_de_la_barre_laterale_lisibles():
    # WCAG 1.4.3 : --fg-very-faint (2,48:1) et --fg-faint (3,96:1) sont sous 4,5:1.
    for selector in (".sidebar-status-detail", ".sidebar-footer-meta", ".sidebar-connection-sub"):
        assert "color: var(--fg-mute)" in _rules(selector)[0], selector
    html = _page("/plan-de-travail")
    assert "Idle" not in html and "Au repos" in html
    assert 'style="color: var(--fg-faint)">Au repos' not in html


def test_R3_lien_d_evitement_vers_le_contenu():
    html = _page("/plan-de-travail")
    body = html[html.index("<body>"):]
    first_link = re.search(r"<a [^>]*>", body).group(0)
    assert 'class="skip-link"' in first_link and 'href="#contenu"' in first_link
    assert re.search(r'<main class="container" id="contenu"', html)


def test_R4_connexions_hors_de_la_navigation():
    html = _page("/cleaner")
    nav = re.search(r'<nav class="sidebar-nav-group"[^>]*>(.*?)</nav>', html, re.S).group(1)
    assert "Connexions" not in nav and "Ollama" not in nav
    assert re.search(r'<section class="sidebar-nav-group" aria-labelledby="sidebar-connections-title">', html)
    assert 'class="ti ti-brain" style="color: var(--warn)" aria-hidden="true"' in html


def test_R5_fiche_offre_dans_la_rubrique_sans_etre_la_page():
    html = _page("/offers/9999")
    assert re.search(r'href="/" class="sidebar-nav-item active"[^>]*aria-current="true"', html)
    assert 'aria-current="page"' not in html
    assert re.search(r'href="/" class="sidebar-nav-item active"[^>]*aria-current="page"', _page("/"))


def test_R6_lien_actif_au_telephone_pas_seulement_par_la_couleur():
    body = _rules(".mobile-nav-item.active")[0]
    assert "font-weight: 700" in body and "box-shadow: inset 3px 0 0" in body


def test_R7_bandeau_des_phases_ne_deborde_pas_a_cote_de_la_barre_laterale():
    body = _rules(".phase-strip")[0]
    assert "repeat(auto-fit, minmax(160px, 1fr))" in body
    assert "repeat(4," not in body


def test_R8_textes_du_gabarit_pas_trop_petits():
    assert "font-size: 12px" in _rules(".footer")[0]
    assert "font-size: inherit" in _rules(".footer small")[0]
    assert "font-size: 11px" in _rules(".sidebar-nav-label")[0]
