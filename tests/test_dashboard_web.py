"""Revue UX du tableau de bord (L2) : une règle par test, nommée « Rn — … »."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from jobmail.db import connect, insert_email, upsert_offer
from jobmail.models import ContractType, OfferExtraction, WorkMode
from jobmail.models import RawEmail
from jobmail.web import app as web_app

CSS = (Path(__file__).resolve().parents[1] / "jobmail" / "web" / "static" / "style.css").read_text(
    encoding="utf-8"
)


def _client(tmp_path, offers=()):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "dash.db"
    settings.llm_provider = "mock"
    client = TestClient(web_app.create_app())
    with connect(settings.db_path) as conn:
        for i, (score, status) in enumerate(offers):
            mail = RawEmail(
                uid=f"u{i}", message_id=f"<u{i}@t>", subject=f"Offre {i}", sender="rh@exemple.test",
                received_at=datetime(2026, 5, 25, 9, 30), body_text="x", body_html="",
            )
            insert_email(conn, mail, job_related=True, matched_keywords=[])
            oid = upsert_offer(
                conn, mail.uid,
                OfferExtraction(title=f"Poste {i}", company="Acme", relevance_score=score,
                                work_mode=WorkMode.REMOTE, contract_type=ContractType.CDI),
            )
            conn.execute("UPDATE offers SET status=? WHERE id=?", (status, oid))
    return client


def _kpis(html: str) -> list[int]:
    return [int(n) for n in re.findall(r'class="kpi-number">(\d+)<', html)]


def test_R1_les_compteurs_ne_dependent_pas_du_filtre(tmp_path):
    client = _client(tmp_path, [(9, "new"), (8, "interesting"), (4, "new")])
    plein = _kpis(client.get("/").text)
    filtre = _kpis(client.get("/?status=interesting").text)
    assert plein == [3, 2, 2, 3]
    assert filtre == plein


def test_R2_le_nombre_affiche_distingue_le_filtre_du_total(tmp_path):
    client = _client(tmp_path, [(9, "new"), (8, "interesting"), (4, "new")])
    html = client.get("/?status=interesting").text
    assert "1 offre sur 3" in html
    assert "3 offres" in client.get("/").text


def test_R3_statuts_et_modes_sont_affiches_en_francais(tmp_path):
    client = _client(tmp_path, [(9, "new"), (8, "interesting")])
    html = client.get("/").text
    body = html[html.index("<tbody>"):html.index("</tbody>")]
    assert "Nouvelle" in body and "Intéressante" in body and "Télétravail" in body
    textes = [t.strip() for t in re.findall(r'<span class="status status-\w+">(.*?)</span>', body, re.S)]
    assert textes == ["Nouvelle", "★ Intéressante"]
    assert '<option value="interesting"' in html and "Intéressante</option>" in html


def test_R4_les_boutons_icones_ont_un_nom_accessible(tmp_path):
    html = _client(tmp_path, [(9, "new")]).get("/").text
    assert 'aria-label="Marquer l’offre intéressante' in html
    assert 'aria-label="Ignorer l’offre' in html
    assert 'aria-label="Voir le détail de l’offre' in html
    assert 'aria-label="Marquer l’offre répondue' in html


def test_R5_le_titre_de_la_page_est_en_francais(tmp_path):
    html = _client(tmp_path).get("/").text
    assert "<h1 class=\"page-header-title\">Tableau de bord</h1>" in html
    assert "<title>Tableau de bord — JobMail</title>" in html


def test_R6_au_telephone_les_offres_sont_des_cartes_sans_defilement_lateral():
    media = CSS[CSS.index("@media (max-width: 900px)"):]
    assert "table.offers { display: block; overflow-x: auto; }" not in media
    assert re.search(r"table\.offers tbody tr\s*\{[^}]*display:\s*grid", media)
    assert re.search(r"table\.offers thead\s*\{[^}]*display:\s*none", media)
