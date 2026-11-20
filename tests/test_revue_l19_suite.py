"""L19, sous-tâches t1 à t5 de la revue UX (rapport docs/revues/L19-revue-ux.md).

Mesures de départ (Chromium, instances de démonstration aux données fictives, 390 et 1440 px) :
- t1 : 33 déclarations de taille entre 10 et 11,9 px, boutons Tailwind du nettoyeur à 10,5 px ;
  après : aucun nœud texte sous 12 px sur les 8 pages, aux deux largeurs ;
- t3 : base vide et sans filtre, « Aucune offre ne matche ce filtre. » ;
- t4 : à 390 px, tableau des règles regex de 370 px dans un cadre de 318 (colonne Expéditeur coupée) ;
- t5 : cases « Je confirme » de 13 × 13 px, en-tête « Backups Thunderbird » de 17 px de haut ;
- t2 : à 390 px, 6 champs, 2 boutons et 7 raccourcis avant la liste (titre à 1 129 px) ; mesures
  du repli en navigateur dans tests/test_filtres_replies.py.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobmail.db import connect, insert_email, upsert_offer
from jobmail.models import OfferExtraction, RawEmail
from jobmail.web import app as web_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "jobmail" / "web"
CSS = (WEB / "static" / "style.css").read_text(encoding="utf-8")
VUE = (ROOT / "frontend" / "src" / "cleaner" / "CleanerApp.vue").read_text(encoding="utf-8")
BUILT_CSS = (WEB / "static" / "assets" / "cleaner.css").read_text(encoding="utf-8")
BUILT_JS = (WEB / "static" / "assets" / "cleaner.js").read_text(encoding="utf-8")


def _rules(selector: str, css: str = CSS) -> list[str]:
    # Corps des règles de ce sélecteur, aussi à l'intérieur d'un @media (précédé de « { »).
    return re.findall(rf"(?:^|[{{}}])\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.M)


def _media(query: str) -> str:
    start = CSS.index(f"@media ({query}) {{")
    depth, i = 0, CSS.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(CSS[i], 0)
        if depth == 0:
            return CSS[start : i + 1]
        i += 1


def _client(tmp_path, offers: int = 0) -> TestClient:
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "l19.db"
    settings.llm_provider = "mock"
    client = TestClient(web_app.create_app())
    with connect(settings.db_path) as conn:
        for i in range(offers):
            mail = RawEmail(
                uid=f"u{i}", message_id=f"<u{i}@exemple.test>", subject=f"Offre {i}",
                sender="rh@exemple.test", received_at=datetime(2026, 11, 10, 9, 30),
                body_text="Texte fictif.", body_html="",
            )
            insert_email(conn, mail, job_related=True, matched_keywords=[])
            upsert_offer(conn, mail.uid, OfferExtraction(title=f"Poste {i}", company="Exemple SA", relevance_score=5))
    return client


# ── t1 : texte d'au moins 12 px, en rem ──────────────────────────────────────────


def test_t1_aucune_taille_de_texte_sous_12_px():
    sources = {"style.css": CSS}
    for path in sorted((WEB / "templates").glob("*.html")):
        sources[path.name] = path.read_text(encoding="utf-8")
    for name, text in sources.items():
        for value in re.findall(r"font-size:\s*([^;\"}]+)", text):
            value = value.strip()
            if value in ("inherit", "100%"):
                continue
            rem = re.fullmatch(r"([\d.]+)rem", value)
            if rem:
                assert float(rem.group(1)) >= 0.75, (name, value)
                continue
            # Une taille relative au parent n'est admise qu'avec un plancher de 12 px.
            assert re.fullmatch(r"max\(0\.75rem, [\d.]+em\)", value), (name, value)


def test_t1_boutons_du_nettoyeur_a_12_px():
    # Jeton text-xs de Tailwind (boutons « sm » du nettoyeur Vue) : 10,5 px avant.
    source = (ROOT / "frontend" / "src" / "styles" / "tailwind.css").read_text(encoding="utf-8")
    assert re.search(r"--text-xs:\s*0\.75rem;", source)
    assert "--text-xs:.75rem" in BUILT_CSS


# ── t3 : l'état vide dit pourquoi ─────────────────────────────────────────────────


def test_t3_base_vide_renvoie_vers_nouveaux_mails(tmp_path):
    html = _client(tmp_path).get("/").text
    assert "Aucune offre pour l'instant." in html
    assert "Lance « Nouveaux mails »" in html
    # Le bouton de l'état vide soumet le formulaire du haut (même relève, même suivi).
    assert '<form id="refresh-form" method="post" action="/refresh"' in html
    assert re.search(r'<button type="submit" form="refresh-form" class="btn btn-primary">\s*<i[^>]*></i>\s*Nouveaux mails', html)
    assert "ne correspond à ces filtres" not in html
    assert not re.search(r"\bmatche\b", html)


def test_t3_filtre_trop_strict_propose_de_tout_afficher(tmp_path):
    html = _client(tmp_path, offers=3).get("/?min_score=10").text
    assert (
        '<p class="muted">Aucune offre ne correspond à ces filtres, sur 3 offres en tout. '
        '<a href="/">Tout afficher</a></p>'
    ) in html
    assert "Aucune offre pour l'instant." not in html
    assert 'form="refresh-form"' not in html
    assert not re.search(r"\bmatche\b", html)


def test_t3_tri_en_francais(tmp_path):
    html = _client(tmp_path, offers=1).get("/").text
    assert "triées par score décroissant" in html
    assert "· desc" not in html


# Le bouton de l'état vide lance bien la relève : vrai clic dans Chromium,
# tests/test_filtres_replies.py::test_le_bouton_de_l_etat_vide_lance_la_releve.


# ── t4 : règles regex au téléphone ────────────────────────────────────────────────


def test_t4_chaque_champ_regex_porte_son_libelle():
    assert '<td data-label="Expéditeur"><input v-model="rule.sender_regex"' in VUE
    assert '<td data-label="Objet"><input v-model="rule.subject_regex"' in VUE
    assert 'data-label":"Expéditeur"' in BUILT_JS  # build Vite à jour


def test_t4_une_regle_par_carte_sous_600_px():
    media = _media("max-width: 600px")
    assert "display: block" in _rules(".regex-rule-table, .regex-rule-table tbody, .regex-rule-table tr, .regex-rule-table td", media)[0]
    assert "display: none" in _rules(".regex-rule-table thead", media)[0]
    assert "content: attr(data-label)" in _rules(".regex-rule-table td::before", media)[0]
    # Plus de défilement dans le cadre : ni largeur minimale des champs, ni hauteur bornée.
    assert "min-width: 0" in _rules(".regex-rule-table input", media)[0]
    assert "overflow: visible" in _rules(".regex-rule-scroll", media)[0]


def test_t4_le_tableau_remplit_son_cadre_sur_ordinateur():
    # .compact-table (760 px au plus) l'emportait sur .regex-rule-table, déclaré avant.
    assert "width: 100%" in _rules(".compact-table.regex-rule-table")[0]


# ── t5 : cibles du nettoyeur ──────────────────────────────────────────────────────


def test_t5_lignes_de_confirmation_de_44_px():
    assert "min-height: 44px" in _rules(".confirm-line,\n.backup-confirm-line")[0]
    box = _rules('.confirm-line input[type="checkbox"]')[0]
    assert "width: 1.25rem" in box and "height: 1.25rem" in box
    # Les deux cases « Je confirme » sont bien dans une ligne de confirmation (libellé = cible).
    template = (WEB / "templates" / "cleaner.html").read_text(encoding="utf-8")
    for name in ("confirm_cleanup", "confirm_temp_cleanup"):
        assert re.search(
            rf'<label class="confirm-line backup-confirm-line">\s*<input type="checkbox" name="{name}"', template
        ), name


def test_t5_en_tete_backups_de_44_px(tmp_path):
    assert "min-height: 44px" in _rules(".backup-details summary")[-1]
    html = _client(tmp_path).get("/cleaner").text
    assert '<details class="filters backup-panel backup-details">' in html


# ── t2 : filtres repliés au téléphone (maquette validée par Sylvain le 2026-11-20) ──


def test_t2_filtres_dans_un_bloc_repliable_rendu_ouvert(tmp_path):
    html = _client(tmp_path, offers=1).get("/").text
    # Rendu ouvert : sans JavaScript, rien ne change ; le script le referme au téléphone.
    assert '<details class="filters filters-fold" open data-filters-fold>' in html
    fold = html[html.index("<details class=\"filters filters-fold\""):html.index("</details>")]
    assert '<form method="get" class="filter-form">' in fold
    assert '<div class="quick-filters">' in fold
    assert '<span class="filters-fold-active">aucun actif</span>' in fold
    assert 'matchMedia("(max-width: 600px), (max-height: 500px)")' in html


@pytest.mark.parametrize("query,expected", [
    ("?min_score=7", "1 actif : score ≥ 7"),
    ("?since_days=7&min_score=5", "2 actifs : 7 derniers jours, score ≥ 5"),
    ("?status=new&techno=Python&sender=exemple.test&esn=hide",
     "4 actifs : Nouvelle, Python, exemple.test, sans ESN"),
    ("?esn=only", "1 actif : ESN seulement"),
])
def test_t2_le_resume_dit_quels_filtres_sont_actifs(tmp_path, query, expected):
    html = _client(tmp_path, offers=1).get("/" + query).text
    assert f'<span class="filters-fold-active">{expected}</span>' in html


def test_t2_resume_affiche_seulement_au_telephone():
    hors_media = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", CSS)
    assert re.search(r"\.filters-fold > \.filters-fold-summary \{ display: none; \}", hors_media)
    media = _media("max-width: 600px), (max-height: 500px")
    summary = _rules(".filters-fold > .filters-fold-summary", media)[0]
    assert "display: flex" in summary and "min-height: 44px" in summary
    assert "font-size: 0.75rem" in _rules(".filters-fold-active", media)[0]


# ── Revue UX r1 : les lignes vides du Nettoyeur ne sont pas des règles ───────────────


def test_r1_ligne_vide_sans_numero_de_regle():
    assert ":class=\"{ 'regex-rule-blank': !rule.sender_regex.trim() && !rule.subject_regex.trim() }\"" in VUE
    assert "regex-rule-blank" in BUILT_JS  # build Vite à jour
    media = _media("max-width: 600px")
    assert "counter-increment: none" in _rules(".regex-rule-table tr.regex-rule-blank", media)[0]
    assert 'content: "Ligne libre"' in _rules(".regex-rule-table tr.regex-rule-blank::before", media)[0]
