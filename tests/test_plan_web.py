"""L7 — page « Plan de travail » : titres publics et états seulement, lus de raf.yaml.

Preuve de non-fuite : la page est rendue depuis un plan synthétique truffé de textes
privés (notes sur plusieurs lignes, guillemets, accents, HTML, lot abandonné, lot
`visible: false` avec `public:`, `public:` qui n'est pas du texte) et aucun n'apparaît ;
même contrôle sur le vrai docs/plan/raf.yaml."""
from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from jobmail.web import app as web_app
from jobmail.web import news as news_mod
from jobmail.web import plan_public
from jobmail.web.plan_public import (
    build_public_plan,
    plan_summary,
    private_texts,
    public_title_problem,
    steps_label,
)

REPO = Path(__file__).resolve().parents[1]

SYNTHETIC_PLAN = """\
version: 1
project: demo
prefix: L
lots:
  - id: L1
    title: Titre brut privé du lot livré numéro un
    public: Une recherche plus rapide
    status: done
    visible: true
    created: 2026-09-01
    finished: 2026-10-01
    notes:
      - { date: 2026-09-02, text: "Note privée « entre guillemets » avec <b>HTML</b> et accents éàü" }
      - date: 2026-09-03
        text: |
          Première ligne d'une note privée sur plusieurs lignes
          Deuxième ligne de la note privée, très confidentielle
    ux: { date: 2026-10-01, verdict: "Verdict UX privé : contraste insuffisant au téléphone" }
    tasks:
      - { id: t1, title: Titre de sous-tâche privée numéro un, status: done }
      - { id: t2, title: Sous-tâche abandonnée et privée, status: dropped, reason: "Raison d'abandon privée et détaillée" }
      - { id: t3, title: Deuxième sous-tâche privée en cours, status: todo }
  - id: L2
    title: Lot abandonné au titre brut privé
    public: Un titre public de lot abandonné
    status: dropped
    visible: true
    reason: Raison privée de l'abandon du lot
  - id: L3
    title: Lot invisible au titre brut privé
    public: Un titre public de lot invisible
    status: todo
  - id: L4
    title: Lot au public numérique au titre privé
    public: 2026
    status: doing
    visible: true
  - id: L5
    title: Revue UX — écran privé du tableau de bord
    status: done
    visible: true
    finished: 2026-09-20
  - id: L6
    title: Lot livré sans public au titre privé
    status: done
    visible: true
    finished: 2026-09-25
  - id: L7
    title: Lot en cours prêt au titre privé
    public: Un tri des offres par date
    status: doing
    visible: true
    tasks:
      - { id: t1, title: Étape privée une du lot sept, status: done }
      - { id: t2, title: Étape privée deux du lot sept, status: done }
  - id: L8
    title: Lot prévu au titre brut privé
    public: 'Un titre avec <b>balise et "guillemets"'
    status: todo
    visible: true
  - id: L9
    title: Lot en cours sans titre public privé
    status: doing
    visible: true
  - id: L10
    title: Lot multi-ligne au titre privé
    public: "Première ligne\\nseconde ligne"
    status: todo
    visible: true
  - id: L11
    title: Lot fusionné numéro un au titre privé
    public: Un même titre pour deux lots
    status: todo
    visible: true
    tasks: [{ id: t1, title: Étape privée du lot onze, status: done }]
  - id: L12
    title: Lot fusionné numéro deux au titre privé
    public: Un même titre pour deux lots
    status: todo
    visible: true
    tasks: [{ id: t1, title: Étape privée du lot douze, status: todo }]
  - id: L13
    title: Correction de sécurité privée
    public: Une correction discrète
    status: done
    visible: true
    finished: 2026-09-26
"""


def _done_lots(n: int) -> str:
    return "".join(
        f"  - id: L{100 + i}\n    title: Lot livré numéro {i} au titre brut\n"
        f"    public: Livraison numéro {i}\n    status: done\n    visible: true\n"
        f"    finished: 2026-08-{10 + i:02d}\n"
        for i in range(n)
    )


@pytest.fixture
def client(tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    return TestClient(web_app.create_app())


@pytest.fixture
def plan_file(monkeypatch, tmp_path):
    path = tmp_path / "raf.yaml"
    path.write_text(SYNTHETIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(plan_public, "PLAN_PATH", path)
    news_dir = tmp_path / "news"
    news_dir.mkdir()
    (news_dir / "nouveautes.json").write_text(
        '{"entries": [{"slug": "2026-09-25-x", "title": "Une liste plus lisible",'
        ' "date": "2026-09-25", "lots": ["L6"], "captures": [], "html": ""}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", news_dir)
    return path


def _sections(page: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'<section class="plan-section" id="([^"]+)".*?</section>', page, re.S):
        out[m.group(1)] = m.group(0)
    return out


def _assert_no_private_text(page: str, raw: object, plan) -> None:
    texts = private_texts(raw, plan)
    assert texts, "aucun texte privé trouvé : le test ne prouverait rien"
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if len(line) < 12:
                continue
            for form in {line, html_mod.escape(line), html_mod.escape(line, quote=False)}:
                assert form not in page, f"texte privé rendu : {line!r}"


# ── Page rendue depuis le plan synthétique ────────────────────────────────────────

def test_synthetic_plan_leaks_no_private_text(client, plan_file):
    page = client.get("/plan-de-travail")
    assert page.status_code == 200
    raw = yaml.safe_load(SYNTHETIC_PLAN)
    _assert_no_private_text(page.text, raw, build_public_plan(raw, {"L6": "Une liste plus lisible"}))
    for forbidden in (
        "Un titre public de lot abandonné", "Un titre public de lot invisible", ">2026<",
        "Première ligne", "<b>balise", "contraste insuffisant", "Raison", "guillemets »",
        "Une correction discrète",
    ):
        assert forbidden not in page.text, forbidden


def test_sections_states_and_titles(client, plan_file):
    page = client.get("/plan-de-travail").text
    sections = _sections(page)
    assert list(sections) == ["en-cours", "prevu", "livre"]
    assert "Un tri des offres par date" in sections["en-cours"]
    assert "Prêt, en attente de livraison" in sections["en-cours"]
    assert "2 étapes faites sur 2" in sections["en-cours"]
    # HTML d'un titre public échappé, jamais interprété.
    assert "Un titre avec &lt;b&gt;balise et &#34;guillemets&#34;" in sections["prevu"]
    assert sections["prevu"].count("Un même titre pour deux lots") == 1
    assert "1 étape faite sur 2" in sections["prevu"]
    livre = sections["livre"]
    assert "Une recherche plus rapide" in livre
    assert "Livré le 1er octobre 2026" in livre
    assert "1 étape faite sur 2" in livre  # sous-tâche abandonnée exclue
    assert "Une liste plus lisible" in livre  # titre de sa Nouveauté
    assert "Revue" not in livre
    assert livre.index("Une recherche plus rapide") < livre.index("Une liste plus lisible")


def test_lot_ids_only_as_element_ids(client, plan_file):
    page = client.get("/plan-de-travail").text
    text = re.sub(r"<[^>]+>", " ", page)
    assert not re.search(r"\bL\d+\b", text)
    assert 'id="lot-L7"' in page


def test_summary_has_no_zero_counts_and_links_to_news(client, plan_file):
    page = client.get("/plan-de-travail").text
    summary = re.search(r'<p class="plan-summary">(.*?)</p>', page, re.S).group(1)
    assert "1 travail en cours" in summary
    assert "2 travaux prévus" in summary
    assert "2 travaux livrés" in summary
    assert "0" not in re.sub(r"<[^>]+>", "", summary)
    assert 'href="/nouveautes"' in _sections(page)["livre"]


def test_only_the_eight_most_recent_deliveries(client, monkeypatch, tmp_path):
    path = tmp_path / "raf.yaml"
    path.write_text("version: 1\nlots:\n" + _done_lots(10), encoding="utf-8")
    monkeypatch.setattr(plan_public, "PLAN_PATH", path)
    page = client.get("/plan-de-travail").text
    livre = _sections(page)["livre"]
    assert livre.count('class="plan-lot"') == 8
    assert "Livraison numéro 9" in livre and "Livraison numéro 1<" not in livre
    assert "Les 8 derniers travaux terminés, sur 10 au total." in livre
    assert "Les prochains travaux seront annoncés ici." in _sections(page)["prevu"]
    summary = re.search(r'<p class="plan-summary">(.*?)</p>', page, re.S).group(1)
    assert "en cours" not in summary and "prévu" not in summary


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "Le plan de travail est introuvable pour le moment."),
        ("lots: [\n  - id: L1\n  title: : :", "Le plan de travail est illisible pour le moment."),
        ("version: 1\n", "Le plan de travail est illisible pour le moment."),
        ("- juste\n- une liste\n", "Le plan de travail est illisible pour le moment."),
    ],
)
def test_missing_or_malformed_plan_gives_an_honest_error(client, monkeypatch, tmp_path, content, message):
    path = tmp_path / "raf.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(plan_public, "PLAN_PATH", path)
    page = client.get("/plan-de-travail")
    assert page.status_code == 200
    assert message in page.text
    assert "Les prochains travaux seront annoncés ici." not in page.text
    assert 'class="plan-section"' not in page.text


def test_plan_link_is_current_on_the_plan_page(client, plan_file):
    page = client.get("/plan-de-travail").text
    assert re.search(r'href="/plan-de-travail" class="sidebar-nav-item active"[^>]*aria-current="page"', page)


# ── Règles pures ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("title", "ok"),
    [
        ("Une page Nouveautés", True),
        (2026, False),
        (None, False),
        ("", False),
        ("a\nb", False),
        ("x" * 81, False),
        ("Lecture du docs/plan", False),
        ("Lu de raf.yaml", False),
        ("Mémoire localStorage", False),
        ("Suite du L6", False),
        ("Correction de sécurité", False),
        ("Jeton d'accès", False),
    ],
)
def test_public_title_rules(title, ok):
    assert (public_title_problem(title) is None) is ok


def test_hidden_lots_are_reported_with_a_reason():
    plan = build_public_plan(yaml.safe_load(SYNTHETIC_PLAN), {"L6": "Une liste plus lisible"})
    hidden = dict(plan.hidden)
    assert set(hidden) == {"L4", "L5", "L9", "L10", "L13"}
    assert "pas du texte" in hidden["L4"]


def test_labels():
    assert plan_summary({"doing": 0, "todo": 0, "done": 0}) == []
    assert steps_label(0, 2) == "0 étape faite sur 2"
    assert steps_label(3, 3) == "3 étapes faites sur 3"


# ── Vrai plan du dépôt ───────────────────────────────────────────────────────────

def test_real_plan_renders_without_private_text(client, monkeypatch):
    monkeypatch.setattr(plan_public, "PLAN_PATH", REPO / "docs" / "plan" / "raf.yaml")
    page = client.get("/plan-de-travail")
    assert page.status_code == 200
    raw = plan_public.load_raw_plan(REPO / "docs" / "plan" / "raf.yaml")
    titles = news_mod.news_titles_by_lot(news_mod.load_news().entries)
    plan = build_public_plan(raw, titles)
    assert not plan.error
    _assert_no_private_text(page.text, raw, plan)


def test_real_plan_public_titles_are_all_conforming():
    raw = plan_public.load_raw_plan(REPO / "docs" / "plan" / "raf.yaml")
    titles = news_mod.news_titles_by_lot(news_mod.load_news().entries)
    plan = build_public_plan(raw, titles)
    bad = [(lot_id, why) for lot_id, why in plan.hidden if "non conforme" in why]
    assert not bad, f"titre public à corriger dans docs/plan/raf.yaml : {bad}"
