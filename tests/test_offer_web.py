"""Revue UX de la fiche offre (L3) : une règle par test, nommée « Rn — … »."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from jobmail.db import connect, insert_email, upsert_offer
from jobmail.models import ContractType, OfferExtraction, RawEmail, WorkMode
from jobmail.web import app as web_app

CSS = (Path(__file__).resolve().parents[1] / "jobmail" / "web" / "static" / "style.css").read_text(
    encoding="utf-8"
)


def _rules(selector: str) -> list[str]:
    return re.findall(rf"(?:^|\}})\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.M)


def _offer_page(tmp_path, *, status="new", score=9) -> str:
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "offer.db"
    settings.llm_provider = "mock"
    client = TestClient(web_app.create_app())
    with connect(settings.db_path) as conn:
        mail = RawEmail(
            uid="u1", message_id="<u1@t>", subject="Offre test",
            sender="une.adresse.vraiment.tres.longue@recrutement-exemple.test",
            received_at=datetime(2026, 5, 25, 9, 30), body_text="Corps du mail de test.", body_html="",
        )
        insert_email(conn, mail, job_related=True, matched_keywords=[])
        oid = upsert_offer(
            conn, mail.uid,
            OfferExtraction(title="Poste test", company="Acme", relevance_score=score,
                            work_mode=WorkMode.HYBRID, contract_type=ContractType.CDI),
        )
        conn.execute("UPDATE offers SET status=? WHERE id=?", (status, oid))
    resp = client.get(f"/offers/{oid}")
    assert resp.status_code == 200
    return resp.text


def test_R1_valeurs_affichees_en_francais(tmp_path):
    html = _offer_page(tmp_path, status="interesting")
    assert "<dd>Hybride</dd>" in html and "<dd>CDI</dd>" in html
    assert "25/05/2026 à 09:30" in html
    assert "Retour au tableau de bord" in html and "Retour au dashboard" not in html
    form = html[html.index('class="status-form"'):html.index("</form>")]
    for libelle in ("Nouvelle", "Intéressante", "Ignorée", "Répondue"):
        assert libelle in form
    # Les valeurs envoyées au serveur ne changent pas.
    assert 'value="interesting"' in form


def test_R2_statut_actuel_annonce_sans_dependre_de_la_couleur(tmp_path):
    html = _offer_page(tmp_path, status="new")
    pressed = re.findall(r'value="(\w+)"\s+aria-pressed="(true|false)"', html)
    assert dict(pressed) == {"new": "true", "interesting": "false", "ignored": "false", "replied": "false"}
    assert "(statut actuel)" in html
    assert any("box-shadow" in b for b in _rules(".status-btn.active"))


def test_R3_libelle_de_l_extrait_ne_contredit_pas_son_etat(tmp_path):
    html = _offer_page(tmp_path)
    summary = re.search(r"<summary>(.*?)</summary>", html, re.S).group(1)
    assert "Afficher" not in summary and "Masquer" not in summary
    assert "Texte du mail" in summary


def test_R4_score_avant_le_contenu_dans_l_ordre_de_lecture(tmp_path):
    html = _offer_page(tmp_path)
    assert html.index('class="offer-sidebar-sticky"') < html.index('class="offer-main"')
    assert any('"side" "main"' in b for b in _rules(".offer-detail-layout"))


def test_R5_aucune_valeur_ne_deborde_au_telephone():
    assert any("min-width: 0" in b for b in _rules(".offer-detail-layout > *"))
    assert any("overflow-wrap: anywhere" in b for b in _rules("dl.grid dd"))


def test_R6_textes_de_la_fiche_au_dessus_de_4_5_pour_1():
    # --fg-very-faint (2,08:1) et --fg-faint (3,3 à 3,8:1) sont sous le seuil WCAG 1.4.3.
    for selector in (".offer-detail h2", "dl.grid dt", ".back", ".offer-meta-loc", ".mail-body", ".score-denom"):
        bodies = _rules(selector)
        assert bodies, selector
        assert all("color: var(--fg-faint)" not in b and "color: var(--fg-very-faint)" not in b for b in bodies), selector


def test_R7_copie_de_l_adresse_annoncee(tmp_path):
    html = _offer_page(tmp_path)
    assert 'data-email="une.adresse.vraiment.tres.longue@recrutement-exemple.test"' in html
    assert 'id="copy-email-status"' in html and 'aria-live="polite"' in html
    assert "onclick=" not in html


def _client(tmp_path) -> TestClient:
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "offer.db"
    settings.llm_provider = "mock"
    return TestClient(web_app.create_app())  # crée le schéma : la base existe, l'offre non


def test_R8_offre_introuvable_page_404_en_francais(tmp_path):
    # Nielsen 9 : l'erreur se reconnaît et on en sort, au lieu du JSON brut de FastAPI.
    client = _client(tmp_path)
    for resp in (
        client.get("/offers/999999"),
        client.post("/offers/999999/status", data={"status": "ignored"}, follow_redirects=False),
    ):
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
        html = resp.text
        assert "Offer not found" not in html and '"detail"' not in html
        assert "<title>Offre introuvable — JobMail</title>" in html
        assert "<h1" in html and "Offre introuvable</h1>" in html
        assert re.search(r'<a href="/" class="btn[^"]*">\s*<i[^>]*></i> Retour au tableau de bord', html)
        assert 'class="sidebar' in html  # dans le gabarit : la navigation reste là


def test_R9_cibles_de_la_fiche_au_moins_40_px_au_toucher():
    # Sous 900 px, les .btn-sm de la fiche (28 px partout ailleurs) font 40 px au moins.
    small = CSS[CSS.index("@media (max-width: 900px)"):]
    small = small[: small.index("\n}\n")]
    bodies = [
        b for b in re.findall(r"([^{}]+)\{([^}]*)\}", small)
        if ".offer-actions-row .btn-sm" in b[0] and ".offer-detail .btn-sm" in b[0]
    ]
    assert bodies, "règle des .btn-sm de la fiche absente sous 900 px"
    height = int(re.search(r"min-height:\s*(\d+)px", bodies[0][1]).group(1))
    assert height >= 40
