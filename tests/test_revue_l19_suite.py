"""L19, sous-tâches t1 à t5 de la revue UX (rapport docs/revues/L19-revue-ux.md).

Mesures de départ (Chromium, instances de démonstration aux données fictives, 390 et 1440 px) :
- t1 : 33 déclarations de taille entre 10 et 11,9 px, boutons Tailwind du nettoyeur à 10,5 px ;
  après : aucun nœud texte sous 12 px sur les 8 pages, aux deux largeurs ;
- t3 : base vide et sans filtre, « Aucune offre ne matche ce filtre. » ;
- t4 : à 390 px, tableau des règles regex de 370 px dans un cadre de 318 (colonne Expéditeur coupée) ;
- t5 : cases « Je confirme » de 13 × 13 px, en-tête « Backups Thunderbird » de 17 px de haut.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

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
    assert "matche" not in html


def test_t3_filtre_trop_strict_propose_de_tout_afficher(tmp_path):
    html = _client(tmp_path, offers=3).get("/?min_score=10").text
    assert (
        '<p class="muted">Aucune offre ne correspond à ces filtres, sur 3 offres en tout. '
        '<a href="/">Tout afficher</a></p>'
    ) in html
    assert "Aucune offre pour l'instant." not in html
    assert 'form="refresh-form"' not in html
    assert "matche" not in html


def test_t3_tri_en_francais(tmp_path):
    html = _client(tmp_path, offers=1).get("/").text
    assert "triées par score décroissant" in html
    assert "· desc" not in html


def test_t3_le_suivi_de_la_releve_vise_les_deux_boutons():
    base = (WEB / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("[data-refresh-status]")' in base
    assert "document.querySelectorAll(`button[form=\"${form.id}\"]`)" in base


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


# ── t2 : maquette seulement, rien dans l'application ─────────────────────────────


def test_t2_maquette_statique_sans_code_dans_l_application():
    maquette = (ROOT / "docs" / "maquettes" / "L19-t2-filtres-replies.html").read_text(encoding="utf-8")
    assert "non implémentée, pour avis" in maquette
    assert 'class="filters filters-fold"' in maquette
    assert "filters-fold" not in (WEB / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "filters-fold" not in CSS
    # Données fictives seulement : aucune adresse mail dans la maquette.
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", maquette)
