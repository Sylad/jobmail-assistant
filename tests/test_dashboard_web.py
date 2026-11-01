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
    assert '<span class="nav-label">Tableau de bord</span>' in html
    assert ">Réinitialiser</a>" in html and ">Reset</a>" not in html


def test_R6_au_telephone_les_offres_sont_des_cartes_sans_defilement_lateral():
    media = CSS[CSS.index("@media (max-width: 900px)"):]
    assert "table.offers { display: block; overflow-x: auto; }" not in media
    assert re.search(r"table\.offers tbody tr\s*\{[^}]*display:\s*grid", media)
    assert re.search(r"table\.offers thead\s*\{[^}]*display:\s*none", media)


def _luminance(hexa: str) -> float:
    canaux = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canaux]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(fg: str, bg: str) -> float:
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _compose(base: str, *couches: tuple[tuple[int, int, int], float]) -> str:
    """Fond réellement vu : la page, puis chaque calque translucide (rgb, alpha) dans l'ordre."""
    rgb = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    for couleur, alpha in couches:
        rgb = [c * (1 - alpha) + k * alpha for c, k in zip(rgb, couleur)]
    return "#" + "".join(f"{round(c):02X}" for c in rgb)


BLANC = (255, 255, 255)


def _jeton(nom: str) -> str:
    return re.search(rf"--{nom}:\s*(#[0-9A-Fa-f]{{6}})", CSS).group(1)


def _regle(selecteur: str) -> str:
    return re.search(re.escape(selecteur) + r"\s*\{([^}]*)\}", CSS).group(1)


def test_R7_mode_date_et_bouton_ignore_atteignent_le_contraste_AA(tmp_path):
    html = _client(tmp_path, [(9, "new")]).get("/").text
    body = html[html.index("<tbody>"):html.index("</tbody>")]
    cellule_mode = re.search(r'<td data-label="Mode"([^>]*)>', body).group(1)
    assert "fg-faint" not in cellule_mode and "fg-very-faint" not in cellule_mode
    fond = _jeton("bg")
    for regle in (_regle("td.col-mode"), _regle(".muted.small"), _regle(".btn-icon.active-ignored")):
        jeton = re.search(r"color:\s*var\(--([\w-]+)\)", regle).group(1)
        assert _contraste(_jeton(jeton), fond) >= 4.5, regle
        assert "opacity" not in regle, regle
    # Pastille « Ignorée » : fond composé page → offers-wrap 2 % → teinte de ligne → survol 4 % → fond de pastille.
    pastille = _regle(".status-ignored")
    jeton = re.search(r"color:\s*var\(--([\w-]+)\)", pastille).group(1)
    fond_pastille = _compose(
        fond, (BLANC, 0.02), ((148, 163, 184), 0.06), (BLANC, 0.04), ((100, 116, 139), 0.1)
    )
    assert _contraste(_jeton(jeton), fond_pastille) >= 4.5, pastille


def test_R7_la_ligne_d_une_offre_ignoree_n_est_pas_attenuee_par_opacite(tmp_path):
    html = _client(tmp_path, [(9, "ignored")]).get("/").text
    ligne = re.search(r'<tr class="([^"]*)"', html[html.index("<tbody>"):]).group(1)
    assert "row-status-ignored" in ligne
    assert "active-ignored" in html
    assert "opacity" not in _regle("tr.row-status-ignored")


def test_R8_les_textes_secondaires_de_l_ecran_atteignent_le_contraste_AA():
    """Libellés de filtre, en-têtes de colonnes, méta, scores faibles, KPI et sous-titre : ≥ 4,5:1
    sur le fond réellement composé (WCAG 2.2 1.4.3, pas de texte « large » à 10–12 px)."""
    bg = _jeton("bg")
    fonds = {
        ".filter-form label": _compose(bg, (BLANC, 0.03)),          # .filters = --surface-alt
        ".quick-filters-label": _compose(bg, (BLANC, 0.03)),
        "table.offers th": _compose(bg, (BLANC, 0.02), (BLANC, 0.03)),
        ".section-header-meta": bg,
        ".pagination-meta": _compose(bg, (BLANC, 0.02)),
        ".kpi-label": _compose(bg, (BLANC, 0.05)),                  # .kpi-card = --surface
        ".page-header-sub": bg,
        "tr.score-3 td:first-child, tr.score-4 td:first-child": _compose(bg, (BLANC, 0.02), (BLANC, 0.04)),
    }
    for selecteur, fond in fonds.items():
        regle = _regle(selecteur)
        jeton = re.search(r"color:\s*var\(--([\w-]+)\)", regle).group(1)
        assert _contraste(_jeton(jeton), fond) >= 4.5, (selecteur, jeton, fond)
        assert "opacity" not in regle, selecteur


# ── L15 : suites de la revue de L2 ─────────────────────────────────────────────

def test_L15_R1_un_statut_inconnu_est_refuse_comme_les_autres_parametres(tmp_path):
    client = _client(tmp_path, [(9, "new")])
    assert client.get("/?status=inconnu").status_code == 422
    assert client.get("/?status=NEW").status_code == 422            # casse exacte attendue


def test_L15_R1_les_statuts_valides_et_le_statut_vide_restent_acceptes(tmp_path):
    client = _client(tmp_path, [(9, "new"), (8, "interesting")])
    for statut in ("new", "interesting", "replied", "ignored"):
        assert client.get(f"/?status={statut}").status_code == 200, statut
    # Le menu « Statut » envoie status= quand « Tous » est choisi.
    vide = client.get("/?status=")
    assert vide.status_code == 200 and "2 offres" in vide.text


def test_L15_R2_le_pluriel_suit_le_nombre_d_offres(tmp_path):
    seule = _client(tmp_path, [(9, "new")]).get("/").text
    assert "1 offre détectée" in seule and "1 offres" not in seule
    assert "1 offre<" in seule  # pied de liste : « 1 offre » sans s
    deux = _client(tmp_path, [(9, "new"), (8, "new")]).get("/").text
    assert "2 offres détectées" in deux and "2 offres<" in deux


def test_L15_R3_la_cellule_score_porte_son_libelle_en_cartes_telephone(tmp_path):
    html = _client(tmp_path, [(9, "new")]).get("/").text
    body = html[html.index("<tbody>"):html.index("</tbody>")]
    assert re.search(r'<td data-label="Score">\s*<strong>9/10</strong>', body)
    assert "<th>Score</th>" in html


def test_L15_R4_le_score_0_a_4_atteint_le_contraste_AA_dans_toutes_ses_regles():
    bg = _jeton("bg")
    survol = _compose(bg, (BLANC, 0.02), (BLANC, 0.04))
    for n in range(0, 5):
        regle = re.search(rf"tr\.score-{n} td:first-child[^{{]*\{{([^}}]*)\}}", CSS).group(1)
        jeton = re.search(r"color:\s*var\(--([\w-]+)\)", regle).group(1)
        assert jeton not in ("fg-faint", "fg-very-faint"), n
        assert _contraste(_jeton(jeton), survol) >= 4.5, n


def _annotation(selecteur: str) -> tuple[float, str | None, float | None]:
    """Ratio actuel et, s'il est écrit, « (était --jeton, n,nn:1) » de la règle (ou de sa ligne de fermeture)."""
    m = re.search(re.escape(selecteur) + r"\s*\{[^}]*\}[^\n]*", CSS)
    note = re.search(r"(\d),(\d\d):1", m.group(0))
    assert note, selecteur
    avant = re.search(r"était --([\w-]+)[^)]*?(\d),(\d\d):1", m.group(0))
    return (float(f"{note.group(1)}.{note.group(2)}"),
            avant.group(1) if avant else None,
            float(f"{avant.group(2)}.{avant.group(3)}") if avant else None)


def test_L15_R5_les_ratios_annotes_dans_le_css_sont_les_ratios_mesures():
    bg = _jeton("bg")
    mute = _jeton("fg-mute")
    ligne = _compose(bg, (BLANC, 0.02))
    ignoree_survol = _compose(bg, (BLANC, 0.02), ((148, 163, 184), 0.06), (BLANC, 0.04))
    mesures = {
        ".sidebar-nav-label": _compose(_jeton("sidebar-bg")),
        ".page-header-sub": bg,
        ".footer": bg,
        ".section-header-meta": bg,
        ".kpi-label": _compose(bg, (BLANC, 0.05)),
        ".filter-form label": _compose(bg, (BLANC, 0.03)),
        ".quick-filters-label": _compose(bg, (BLANC, 0.03)),
        "table.offers th": _compose(bg, (BLANC, 0.02), (BLANC, 0.03)),
        ".pagination-meta": ligne,
        "tr.score-3 td:first-child, tr.score-4 td:first-child": _compose(bg, (BLANC, 0.02), (BLANC, 0.04)),
        ".muted.small": ligne,
        "td.col-mode": ligne,
        ".btn-icon.active-ignored": _compose(bg, (BLANC, 0.02), ((148, 163, 184), 0.06), (BLANC, 0.04), (BLANC, 0.05)),
        ".status-ignored": _compose(ignoree_survol, ((100, 116, 139), 0.1)),
    }
    for selecteur, fond in mesures.items():
        actuel, ancien, ratio_ancien = _annotation(selecteur)
        assert abs(actuel - _contraste(mute, fond)) < 0.006, (selecteur, actuel, round(_contraste(mute, fond), 3))
        if ancien:  # « était --fg-faint, 3,75:1 » : le ratio de l'ancien jeton sur le même fond
            assert abs(ratio_ancien - _contraste(_jeton(ancien), fond)) < 0.006, (
                selecteur, ancien, ratio_ancien, round(_contraste(_jeton(ancien), fond), 3))
