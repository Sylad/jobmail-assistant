"""L19 — revue UX « bonnes pratiques d'une appli web standard » : les écarts corrigés dans le lot.

Mesures de départ (Chromium + axe-core 4.10, 320 à 1440 px, rapport docs/revues/L19-revue-ux.md) :
- une adresse inconnue rendait le JSON brut {"detail":"Not Found"} (axe : html-has-lang,
  document-title, page-has-heading-one ; Nielsen 9) ;
- étiquettes des cartes Haute pertinence / Mails ingérés à 3,29:1 et raccourcis du filtre à
  3,49:1 (WCAG 1.4.3, 4,5:1 attendu) ;
- lien « Tout afficher » de l'état vide distingué par la seule couleur, 1,74:1 avec le texte
  (WCAG 1.4.1, axe link-in-text-block) ;
- lien « Retour au tableau de bord » de 15 px de haut (WCAG 2.5.8, 24 px).
"""
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


def _token(name: str) -> str:
    return re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})", CSS).group(1)


def _lum(hex_color: str) -> float:
    def chan(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Fonds mesurés par axe sous ces éléments (surface translucide composée sur --bg).
KPI_CARD_BG = "#1b2335"
FILTER_PANEL_BG = "#161e30"


def _client() -> TestClient:
    return TestClient(web_app.create_app())


def test_adresse_inconnue_page_html_en_francais():
    resp = _client().get("/une-page-qui-n-existe-pas", headers={"accept": "text/html"})
    assert resp.status_code == 404
    html = resp.text
    assert '<html lang="fr"' in html
    assert "<title>Page introuvable — JobMail</title>" in html
    assert '<h1 id="not-found-title" class="page-header-title">Page introuvable</h1>' in html
    assert 'href="/" class="btn btn-primary not-found-back"' in html
    assert '"detail"' not in html
    assert "mal recopié" in html


def test_offre_introuvable_garde_son_message():
    resp = _client().get("/offers/987654", headers={"accept": "text/html"})
    assert resp.status_code == 404
    assert "<title>Offre introuvable — JobMail</title>" in resp.text
    assert "Cette offre n'existe pas ou plus" in resp.text


def test_scan_ou_deplacement_expire_garde_son_message():
    # L19/t6 : un 404 levé par une route existante affiche son propre détail, pas le
    # texte « lien mal recopié » réservé aux adresses inconnues.
    client = _client()
    for path, message in (
        ("/cleaner/scan/result/inconnu", "Scan introuvable."),
        ("/cleaner/move/status/inconnu/result", "Déplacement introuvable."),
    ):
        resp = client.get(path, headers={"accept": "text/html"})
        assert resp.status_code == 404, path
        assert "<title>Page introuvable — JobMail</title>" in resp.text
        assert message in resp.text, path
        assert "mal recopié" not in resp.text, path
    # Les clients JSON reçoivent le même détail.
    resp = client.get("/cleaner/scan/status/inconnu", headers={"accept": "application/json"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Scan introuvable."}


def test_api_et_clients_non_html_gardent_le_json():
    client = _client()
    for path, headers in (
        ("/api/inconnue", {"accept": "text/html"}),
        ("/static/inconnu.css", {"accept": "text/html"}),
        ("/une-page-qui-n-existe-pas", {"accept": "application/json"}),
    ):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 404, path
        assert resp.json() == {"detail": "Not Found"}, path


def test_etiquettes_kpi_et_raccourcis_contraste_4_5():
    mute = _token("fg-mute")
    for selector in (".kpi-green .kpi-tag", ".kpi-blue .kpi-tag"):
        assert "color: var(--fg-mute)" in _rules(selector)[0], selector
    assert "color: var(--fg-mute)" in _rules(".chip-link")[0]
    assert _ratio(mute, KPI_CARD_BG) >= 4.5
    assert _ratio(mute, FILTER_PANEL_BG) >= 4.5
    # Le jeton d'avant échoue bien : le test mesure ce qu'il prétend mesurer.
    assert _ratio(_token("fg-faint"), KPI_CARD_BG) < 4.5


def test_lien_dans_un_texte_gris_est_souligne():
    assert "text-decoration: underline" in _rules("p.muted a")[0]
    # Le lien lui-même (état vide d'un filtre trop strict) : tests/test_revue_l19_suite.py (t3).


def test_lien_retour_cible_de_24_px():
    assert "min-height: 24px" in _rules(".back")[0]
    assert "display: inline-flex" in _rules(".back")[0]


def test_texte_gris_contraste_4_5():
    assert "color: var(--fg-mute)" in _rules(".muted")[0]
    # Fond de la liste des offres mesuré par axe sous l'état vide.
    assert _ratio(_token("fg-mute"), "#141c2e") >= 4.5


def test_les_deux_aside_de_la_fiche_offre_ont_un_nom():
    from datetime import datetime

    from jobmail.db import connect, insert_email, upsert_offer
    from jobmail.models import OfferExtraction, RawEmail

    settings = web_app.get_settings()
    client = _client()
    with connect(settings.db_path) as conn:
        mail = RawEmail(
            uid="l19", message_id="<l19@t>", subject="Offre test", sender="a@exemple.test",
            received_at=datetime(2026, 11, 20, 9, 0), body_text="Corps.", body_html="",
        )
        insert_email(conn, mail, job_related=True, matched_keywords=[])
        oid = upsert_offer(conn, mail.uid, OfferExtraction(title="Poste", company="Acme"))
    html = client.get(f"/offers/{oid}").text
    labels = re.findall(r'<aside class="[^"]*" aria-label="([^"]+)"', html)
    assert len(labels) == 2 and len(set(labels)) == 2, labels
    assert len(re.findall(r"<aside\b", html)) == 2


def test_chaque_100vh_est_suivi_de_sa_valeur_dvh():
    # skill interface-utilisable §5 : 100vh passe sous la barre du navigateur mobile ; 100vh reste
    # en repli pour les navigateurs sans dvh, la ligne dvh qui suit l'emporte.
    lines = CSS.splitlines()
    vh = [i for i, line in enumerate(lines) if re.search(r"\b100vh\b", line)]
    assert vh
    for i in vh:
        prop = lines[i].split(":")[0].strip()
        following = "\n".join(lines[i + 1 : i + 4])
        assert re.search(rf"\b{re.escape(prop)}:\s*100dvh", following), lines[i]
