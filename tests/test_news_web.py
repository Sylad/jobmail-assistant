"""L6 — page Nouveautés : rendu depuis le JSON compilé par cadence (entrées synthétiques
seulement), corps filtré par liste blanche, captures, état vide et erreur honnêtes, et
fraîcheur du JSON versionné."""
from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import zlib
from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobmail.web import app as web_app
from jobmail.web import news as news_mod
from jobmail.web.news import sanitize_news_html

REPO = Path(__file__).resolve().parents[1]
ENTRIES_DIR = REPO / "docs" / "nouveautes"
COMMITTED = REPO / "jobmail" / "web" / "static" / "nouveautes-data"


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


SYNTHETIC = [
    {
        "slug": "2026-10-02-une-page-de-demonstration",
        "title": "Une page de démonstration",
        "date": "2026-10-02",
        "lots": ["L90"],
        "captures": ["captures/demo-telephone.png"],
        "html": "<p>Texte <strong>gras</strong> et <code>code</code>.</p>\n"
        "<ul><li>Un point</li><li>Un <a href=\"https://example.org/doc\">lien</a></li></ul>",
    },
    {
        "slug": "2026-10-01-premiere-entree",
        "title": "Première entrée",
        "date": "2026-10-01",
        "lots": ["L89"],
        "captures": ["captures/a.png", "captures/b.png"],
        "html": "<p>Avant.</p>",
    },
]


def _write_news(directory: Path, entries: list[dict]) -> Path:
    (directory / "captures").mkdir(parents=True, exist_ok=True)
    for e in entries:
        for c in e.get("captures", []):
            (directory / c).write_bytes(_png(390, 844))
    (directory / "nouveautes.json").write_text(
        json.dumps({"project": "demo", "generated": "x", "entries": entries}), encoding="utf-8"
    )
    return directory


@pytest.fixture
def client(monkeypatch, tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web.db"
    return TestClient(web_app.create_app())


@pytest.fixture
def news_dir(monkeypatch, tmp_path):
    directory = _write_news(tmp_path / "nouveautes-data", SYNTHETIC)
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", directory)
    return directory


def _text(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", html))


# ── Page ──────────────────────────────────────────────────────────────────────────

def test_page_lists_entries_most_recent_first_with_french_dates(client, news_dir):
    page = client.get("/nouveautes")
    assert page.status_code == 200
    html = page.text
    first = html.index('id="2026-10-02-une-page-de-demonstration"')
    second = html.index('id="2026-10-01-premiere-entree"')
    assert first < second
    assert "2 octobre 2026" in html
    assert "1er octobre 2026" in html
    assert '<time datetime="2026-10-02">' in html
    assert "<p>Texte <strong>gras</strong> et <code>code</code>.</p>" in html
    assert '<a href="https://example.org/doc">lien</a>' in html


def test_title_is_plain_text_and_copy_button_sits_by_the_date(client, news_dir):
    html = client.get("/nouveautes").text
    article = html[html.index('id="2026-10-02-une-page-de-demonstration"'):]
    article = article[: article.index("</article>")]
    h2 = re.search(r"<h2[^>]*>(.*?)</h2>", article, re.S).group(1)
    assert "<a" not in h2 and "Une page de démonstration" in h2
    assert article.index("<time") < article.index("news-copy") < article.index("<h2")
    assert 'data-slug="2026-10-02-une-page-de-demonstration"' in article
    assert "Copier le lien" in article
    # Adresse affichée seulement en cas d'échec de la copie, sous le titre.
    assert article.index("<h2") < article.index("news-permalink")


def test_captures_open_larger_and_carry_alt_and_size(client, news_dir):
    html = client.get("/nouveautes").text
    assert 'href="/static/nouveautes-data/captures/demo-telephone.png"' in html
    assert 'alt="Capture d&#39;écran : Une page de démonstration"' in html
    assert 'alt="Capture d&#39;écran 2 sur 2 : Première entrée"' in html
    assert 'width="390"' in html and 'height="844"' in html
    assert "<dialog" in html and "news-lightbox" in html


def test_status_line_and_live_region_are_present(client, news_dir):
    html = client.get("/nouveautes").text
    assert re.search(r'class="news-since"[^>]*role="status"', html)
    assert re.search(r'id="news-copy-status"[^>]*role="status"', html)


def test_empty_journal_shows_honest_empty_state(client, monkeypatch, tmp_path):
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", _write_news(tmp_path / "vide", []))
    page = client.get("/nouveautes")
    assert page.status_code == 200
    assert "Aucune nouveauté publiée pour l'instant." in page.text


def test_missing_build_is_an_empty_journal(client, monkeypatch, tmp_path):
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", tmp_path / "absent")
    page = client.get("/nouveautes")
    assert page.status_code == 200
    assert "Aucune nouveauté publiée" in page.text


def test_unreadable_build_gives_an_error_state_not_a_500(client, monkeypatch, tmp_path):
    broken = tmp_path / "casse"
    broken.mkdir()
    (broken / "nouveautes.json").write_text("{ pas du json", encoding="utf-8")
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", broken)
    page = client.get("/nouveautes")
    assert page.status_code == 200
    assert "Le journal des nouveautés est illisible pour le moment." in _text(page.text)
    assert "Aucune nouveauté publiée" not in page.text


def test_every_page_carries_the_news_index_for_the_badge(client, news_dir):
    for path in ("/", "/cleaner", "/nouveautes"):
        html = client.get(path).text
        m = re.search(r'<script type="application/json" id="jm-news-index">(.*?)</script>', html, re.S)
        assert m, path
        assert json.loads(m.group(1)) == [
            {"slug": "2026-10-02-une-page-de-demonstration", "date": "2026-10-02"},
            {"slug": "2026-10-01-premiere-entree", "date": "2026-10-01"},
        ]
        assert '<script src="/static/news-core.js' in html
        assert '<script src="/static/news.js' in html


def test_news_index_cannot_close_its_script_tag(client, monkeypatch, tmp_path):
    entries = [{**SYNTHETIC[1], "slug": "x</script><script>alert(1)</script>", "captures": []}]
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", _write_news(tmp_path / "evil", entries))
    html = client.get("/").text
    assert "<script>alert(1)" not in html


# ── Liste blanche du corps ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<p>a <strong>b</strong></p>", "<p>a <strong>b</strong></p>"),
        ("<p>x<script>alert(1)</script>y</p>", "<p>xy</p>"),
        ('<p><img src=x onerror="alert(1)">z</p>', "<p>z</p>"),
        ('<a href="javascript:alert(1)">clic</a>', "clic"),
        ('<a href=" javascript:alert(1)">clic</a>', "clic"),
        ('<a href="https://ex.org/?a=1&amp;b=2" onclick="x()">ok</a>', '<a href="https://ex.org/?a=1&amp;b=2">ok</a>'),
        ('<p style="color:red" class="x">t</p>', "<p>t</p>"),
        ("<p>&lt;b&gt; reste du texte</p>", "<p>&lt;b&gt; reste du texte</p>"),
        ("<p>non fermé", "<p>non fermé</p>"),
        ("</p></ul>texte", "texte"),
        ("<iframe src=x>dedans</iframe>après", "après"),
        ('<a href="/nouveautes#x">relatif</a>', '<a href="/nouveautes#x">relatif</a>'),
        (None, ""),
        (42, ""),
    ],
)
def test_sanitizer_keeps_only_the_allow_list(raw, expected):
    assert sanitize_news_html(raw) == expected


def test_malformed_entries_are_skipped(client, monkeypatch, tmp_path):
    entries = [
        {"slug": "", "title": "Sans slug", "date": "2026-10-02", "html": ""},
        {"slug": "sans-date", "title": "Sans date", "date": "hier", "html": ""},
        {"slug": "capture-hors", "title": "Capture hors dossier", "date": "2026-10-02",
         "captures": ["../../secret.png", "/etc/x.png", "captures/ok.png"], "html": ""},
        "pas un objet",
    ]
    directory = _write_news(tmp_path / "mal", [])
    (directory / "nouveautes.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    monkeypatch.setattr(news_mod, "NEWS_DATA_DIR", directory)
    html = client.get("/nouveautes").text
    assert "Sans slug" not in html and "Sans date" not in html
    assert "secret.png" not in html and "/etc/x.png" not in html
    assert "/static/nouveautes-data/captures/ok.png" in html


# ── Fraîcheur du JSON versionné ───────────────────────────────────────────────────

def _committed() -> dict:
    return json.loads((COMMITTED / "nouveautes.json").read_text(encoding="utf-8"))


def _entry_files() -> list[str]:
    if not ENTRIES_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in ENTRIES_DIR.glob("*.md") if p.name.lower() != "readme.md"
    )


def test_committed_build_exists_and_has_one_entry_per_file():
    assert (COMMITTED / "nouveautes.json").is_file(), "lancer scripts/build-news.sh"
    assert sorted(e["slug"] for e in _committed()["entries"]) == _entry_files()


def test_committed_captures_exist_and_no_cadence_index_page():
    for e in _committed()["entries"]:
        for c in e["captures"]:
            assert (COMMITTED / c).is_file(), f"{e['slug']} : {c} manquante"
    assert not (COMMITTED / "index.html").exists()


def _stable(entries: list[dict]) -> list[tuple]:
    """Parties qui ne dépendent pas de la version de cadence : ordre, slug, titre, date,
    lots, noms des captures (le HTML rendu peut changer d'une version à l'autre)."""
    return [
        (e["slug"], e["title"], e["date"], tuple(e.get("lots", [])), tuple(e["captures"]))
        for e in entries
    ]


def test_committed_build_is_up_to_date_with_docs_nouveautes(tmp_path):
    cadence = shutil.which("cadence")
    if cadence is None:
        pytest.skip(
            "cadence absent du PATH : comparaison avec une compilation fraîche impossible "
            "(slugs comparés aux fichiers par test_committed_build_exists_and_has_one_entry_per_file)"
        )
    out = tmp_path / "fresh"
    res = subprocess.run([cadence, "news", "build", "-o", str(out)], cwd=REPO,
                         capture_output=True, text=True)
    assert res.returncode == 0, f"cadence news build en échec : {res.stderr[-1000:]}"
    fresh = json.loads((out / "nouveautes.json").read_text(encoding="utf-8"))
    assert _stable(_committed()["entries"]) == _stable(fresh["entries"]), (
        "JSON périmé : lancer scripts/build-news.sh"
    )
    for c in {c for e in fresh["entries"] for c in e["captures"]}:
        assert (COMMITTED / c).read_bytes() == (out / c).read_bytes(), f"{c} différente"


# ── Navigation ────────────────────────────────────────────────────────────────────

def test_home_links_to_news_and_plan_in_both_navigations(client, news_dir):
    html = client.get("/").text
    for nav_class in ("sidebar-nav-item", "mobile-nav-item"):
        assert re.search(rf'href="/nouveautes" class="{nav_class}\s', html), nav_class
        assert re.search(rf'href="/plan-de-travail" class="{nav_class}\s', html), nav_class
    assert html.count("data-news-badge ") + html.count("data-news-badge>") >= 2
    assert re.search(r'href="/" class="sidebar-nav-item active"[^>]*aria-current="page"', html)


def test_news_link_is_current_on_the_news_page(client, news_dir):
    html = client.get("/nouveautes").text
    assert re.search(r'href="/nouveautes" class="sidebar-nav-item active"[^>]*aria-current="page"', html)
    assert not re.search(r'href="/"[^>]*aria-current', html)


def test_captures_are_served_from_the_compiled_folder(news_dir, tmp_path):
    settings = web_app.get_settings()
    settings.db_path = tmp_path / "web2.db"
    client = TestClient(web_app.create_app())  # monté après le monkeypatch du dossier
    res = client.get("/static/nouveautes-data/captures/demo-telephone.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert client.get("/static/nouveautes-data/nouveautes.json").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_logo_uses_the_shipped_svg_not_a_missing_icon_glyph(client, news_dir):
    html = client.get("/").text
    # ti-mail-spark n'existe pas dans la police d'icônes : carré violet vide.
    assert "ti-mail-spark" not in html
    logos = re.findall(r'<img class="app-logo[^"]*" src="([^"?]+)', html)
    assert len(logos) == 2  # barre latérale et barre du haut
    for src in logos:
        assert src == "/static/favicon.svg"
        assert client.get(src).status_code == 200
