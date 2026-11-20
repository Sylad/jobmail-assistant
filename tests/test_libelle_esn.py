"""L22 — le filtre ESN porte le même libellé partout au tableau de bord : option du
formulaire, raccourci et résumé des filtres actifs (Nielsen 4, cohérence et standards).
Le libellé décrit un état, comme les autres résumés (« Nouvelle », « score ≥ 7 »)."""
from __future__ import annotations

import html as html_lib
import re

import pytest
from fastapi.testclient import TestClient

from jobmail.web import app as web_app

LIBELLES = {"hide": "Sans ESN", "only": "ESN seulement"}


def _page(tmp_path, query: str) -> str:
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "l22.db"
    settings.llm_provider = "mock"
    resp = TestClient(web_app.create_app()).get("/" + query)
    assert resp.status_code == 200
    return resp.text


def _texte(fragment: str) -> str:
    return html_lib.unescape(re.sub(r"\s+", " ", fragment)).strip()


@pytest.mark.parametrize("mode,libelle", LIBELLES.items())
def test_option_raccourci_et_resume_disent_le_meme_mot(tmp_path, mode, libelle):
    page = _page(tmp_path, f"?esn={mode}")
    option = re.search(rf'<option value="{mode}"[^>]*>([^<]*)</option>', page)
    raccourci = re.search(rf'href="\?esn={mode}">([^<]*)</a>', page)
    resume = re.search(r'<span class="filters-fold-active">([^<]*)</span>', page)
    assert option and raccourci and resume
    assert _texte(option.group(1)) == libelle
    assert _texte(raccourci.group(1)) == libelle
    assert _texte(resume.group(1)) == f"1 actif : {libelle}"


def test_plus_de_verbe_masquer_ni_de_minuscule_divergente(tmp_path):
    page = _page(tmp_path, "?esn=hide")
    assert "Masquer ESN" not in page
    assert "sans ESN" not in page
