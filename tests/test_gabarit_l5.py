"""Revue UX du gabarit commun (L5) : une règle par test, nommée « Rn — … »."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
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
    assert re.search(r'<section class="sidebar-nav-group"[^>]*>.*?ti-brain.*?</section>', html, re.S)


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


# ── L5/t1, t2, t3, t5 : un seul état, le même partout, tenu à jour sans recharger ─────────

PAGES = ("/", "/cleaner", "/nouveautes", "/plan-de-travail", "/offers/9999")


def _sidebar_footer(html: str) -> str:
    return re.search(r'<div class="sidebar-footer">(.*?)</aside>', html, re.S).group(1)


def _mobile_status(html: str) -> str:
    return re.search(r'<div class="mobile-status[^"]*" data-shell-status>(.*?)</header>', html, re.S).group(1)


@pytest.fixture(autouse=True)
def _aucun_traitement(monkeypatch):
    # Ni job laissé par un autre test, ni `jobmail watch` réel sur la machine.
    monkeypatch.setattr(web_app, "_refresh_job", None)
    monkeypatch.setattr(web_app, "_reanalysis_job", None)
    monkeypatch.setattr(web_app, "_pipeline_process_active", lambda: (False, None))
    # Réglages partagés : un autre test a pu activer IMAP ou changer de fournisseur.
    settings = web_app.get_settings()
    monkeypatch.setattr(settings, "imap_host", "")
    monkeypatch.setattr(settings, "llm_provider", "mock")


@pytest.fixture
def running_refresh(monkeypatch):
    job = web_app.RefreshJob(id="test")
    monkeypatch.setattr(web_app, "_refresh_job", job)
    return job


def test_R9_meme_etat_au_repos_et_bloc_imap_sur_toutes_les_pages():
    for path in PAGES:
        html = _page(path)
        footer = _sidebar_footer(html)
        assert "Au repos" in footer and re.search(r"\d+ mails? ingérés?", footer), path
        assert "En cours" not in footer, path
        assert '<div class="sidebar-connection-label">IMAP</div>' in html, path
        assert "Désactivé" in html, path


def test_R10_traitement_en_cours_vu_sur_toutes_les_pages(running_refresh):
    for path in PAGES:
        html = _page(path)
        assert "En cours" in _sidebar_footer(html), path
        assert "Au repos" not in _sidebar_footer(html), path
        assert "Analyse des nouveaux mails" in _mobile_status(html), path
    status = TestClient(web_app.create_app()).get("/api/shell-status").json()
    assert status["running"] is True and status["label"] == "En cours"
    assert status["summary"] == "Analyse des nouveaux mails"


def test_R11_reanalyse_en_cours_avec_avancement(monkeypatch):
    job = web_app.ReanalysisJob(id="r", total_count=4, processed_count=1)
    monkeypatch.setattr(web_app, "_reanalysis_job", job)
    html = _page("/plan-de-travail")
    assert "Réanalyse des offres" in _sidebar_footer(html)
    assert re.search(r'role="progressbar"[^>]*aria-valuenow="25"', html)
    assert 'style="width: 25%"' in html


def test_R12_pas_de_rechargement_automatique_meme_pendant_un_traitement(running_refresh):
    for path in PAGES:
        html = _page(path)
        assert 'http-equiv="refresh"' not in html, path
        assert '<script src="/static/shell-status.js' in html, path
        assert re.search(r'<script type="application/json" id="jm-shell-status">\{.*"running": true', html), path


def test_R13_api_et_page_disent_le_meme_etat():
    client = TestClient(web_app.create_app())
    status = client.get("/api/shell-status").json()
    assert set(status) == {"running", "label", "summary", "meta", "progress", "ollama", "imap"}
    html = client.get("/nouveautes").text
    embedded = re.search(r'id="jm-shell-status">(.*?)</script>', html).group(1)
    assert json.loads(embedded) == status


@pytest.mark.parametrize(
    ("provider", "reachable", "state", "label"),
    [("mock", None, "off", "Non utilisé"), ("ollama", True, "ok", "Joignable"), ("ollama", False, "warn", "Injoignable")],
)
def test_R14_couleur_de_l_icone_ollama_suit_l_etat_ecrit(monkeypatch, provider, reachable, state, label):
    settings = web_app.get_settings()
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(web_app, "_ollama_reachable", lambda _url: reachable)
    html = _page("/cleaner")
    connections = re.search(r'aria-labelledby="sidebar-connections-title">(.*?)</section>', html, re.S).group(1)
    assert f'class="sidebar-connection conn-{state}" data-shell-ollama' in connections
    assert f"<span data-shell-ollama-label>{label}</span>" in connections
    assert "style=\"color: var(--warn)\"" not in connections
    assert f'<span class="conn-{state}" data-shell-ollama>' in _mobile_status(html)
    for cls, var in (("ok", "--ok"), ("warn", "--warn"), ("off", "--fg-mute")):
        assert f"color: var({var})" in _rules(f".conn-{cls} .conn-icon")[0]


def test_R15_sonde_ollama_mise_en_cache(monkeypatch):
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, timeout: calls.append(url) or _Resp())
    web_app._ollama_probe_cache.clear()
    assert web_app._ollama_reachable("http://ollama.test:11434") is True
    assert web_app._ollama_reachable("http://ollama.test:11434") is True
    assert calls == ["http://ollama.test:11434/api/tags"]
    web_app._ollama_probe_cache.clear()


def test_R16_etat_et_connexions_au_telephone():
    html = _page("/plan-de-travail")
    header = re.search(r'<header class="mobile-bar">(.*?)</header>', html, re.S).group(1)
    assert "data-shell-status" in header and 'role="status"' in header
    mobile = _mobile_status(html)
    assert "Au repos" in mobile and "Ollama : " in mobile and "IMAP : Désactivé" in mobile
    # Affichée sous 900 px seulement, avec la barre du haut qui la contient.
    block = re.search(r"@media \(max-width: 900px\) \{\n  \.mobile-bar \{(.*?)\n\}", CSS, re.S).group(1)
    assert re.search(r"\.mobile-status \{\s*display: flex;", block)


# Correction de revue L5 : « Traitement terminé · recharger la page » recharge par un GET.
def _reload_link(html: str) -> tuple[str, str]:
    m = re.search(r'id="jm-shell-reload" data-method="([A-Z]+)" data-href="([^"]*)"', html)
    assert m, "adresse de rechargement absente"
    return m.group(1), m.group(2)


def test_R20_page_get_rechargee_par_son_adresse():
    client = TestClient(web_app.create_app())
    html = client.get("/?status=new").text
    assert _reload_link(html) == ("GET", "/?status=new")
    assert _reload_link(client.get("/nouveautes").text) == ("GET", "/nouveautes")


@pytest.mark.parametrize(
    "path",
    ["/cleaner/scan", "/cleaner/backups/cleanup", "/cleaner/temp/cleanup", "/cleaner/move-to-delete"],
)
def test_R21_page_rendue_par_un_post_rechargee_par_un_get_qui_existe(path):
    client = TestClient(web_app.create_app())
    response = client.post(path, data={})
    assert "data-shell-done" in response.text, path
    method, href = _reload_link(response.text)
    assert method == "POST"
    assert href == "/cleaner"
    # Le GET de l'adresse POST donnerait 405 (ou une redirection) ; celle-ci répond la page.
    reloaded = client.get(href, follow_redirects=False)
    assert reloaded.status_code == 200
    assert "data-shell-done" in reloaded.text
