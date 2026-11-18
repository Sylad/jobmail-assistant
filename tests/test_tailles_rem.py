"""L8 — tailles de texte en rem sur une racine à 100 %, barre du haut du téléphone sur une
rangée. Le rendu (mêmes pixels à 16 px, une rangée de 300 à 900 px, aucun débordement) a été
mesuré dans un navigateur (voir le rapport de lot) ; ici, les règles qui le garantissent."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from jobmail.web import app as web_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "jobmail" / "web"
CSS = (WEB / "static" / "style.css").read_text(encoding="utf-8")


def _rules(selector: str) -> list[str]:
    return re.findall(rf"(?:^|\}})\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.M)


def test_la_racine_suit_la_taille_choisie_dans_le_navigateur():
    assert "font-size: 100%" in _rules("html")[0]
    assert "font-size: 0.875rem" in _rules("body")[0]  # 14 px à la taille par défaut
    assert "font-size" not in _rules(":root")[0]


def test_aucune_taille_de_texte_en_pixels():
    sources = {"style.css": CSS}
    for path in sorted((WEB / "templates").glob("*.html")):
        sources[path.name] = path.read_text(encoding="utf-8")
    for name, text in sources.items():
        assert not re.findall(r"font-size:\s*[\d.]+px", text), name


def test_le_nettoyeur_vue_rend_les_memes_pixels():
    # Tailwind compte en rem : ses jetons sont recomptés sur 16 px (3,5 px, 10,5 px, 12,25 px).
    built = (WEB / "static" / "assets" / "cleaner.css").read_text(encoding="utf-8")
    for token in ("--spacing:.21875rem", "--text-xs:.65625rem", "--text-sm:.765625rem"):
        assert token in built, token


def _mobile_bar(html: str) -> str:
    return re.search(r'<header class="mobile-bar">(.*?)</header>', html, re.S).group(1)


def test_barre_du_telephone_logo_et_liens_sur_une_rangee():
    bar = _mobile_bar(TestClient(web_app.create_app()).get("/").text)
    row = re.search(r'<div class="mobile-bar-row">(.*?)</nav>', bar, re.S).group(1)
    assert 'class="mobile-bar-brand"' in row and 'class="mobile-nav"' in row
    assert "flex-wrap: wrap" in _rules(".mobile-nav")[0]  # texte agrandi : à la ligne, pas rogné


def test_libelle_court_au_debut_du_nom_accessible():
    # WCAG 2.5.3 : le libellé visible fait partie du nom accessible (le libellé complet).
    bar = _mobile_bar(TestClient(web_app.create_app()).get("/").text)
    pairs = re.findall(
        r'<span class="nav-label">([^<]+)</span>\s*<span class="nav-label-short" aria-hidden="true">([^<]+)</span>',
        bar,
    )
    assert len(pairs) == 4
    for full, short in pairs:
        assert full.startswith(short), (full, short)


def test_un_bouton_masque_ne_s_affiche_pas():
    # « Arrêter » (hidden au repos) restait affiché et faisait déborder le panneau sous 311 px.
    assert "display: none" in _rules(".btn[hidden]")[0]
