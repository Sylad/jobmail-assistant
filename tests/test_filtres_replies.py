"""L19/t2 — filtres du tableau de bord repliés au téléphone, et bouton de l'état vide, dans Chromium.

Maquette validée par Sylvain le 2026-11-20 (docs/maquettes/L19-t2-filtres-replies.html) : sous
600 px de large ou 500 px de haut, formulaire et raccourcis passent derrière « Filtres », replié
par défaut, dont le résumé dit quels filtres sont actifs ; ailleurs, rien ne change. Avant, à
390 × 844, le titre « Offres détectées » commençait à 1 129 px.

Un `<details>` fermé garde des boîtes dans Chromium (`content-visibility`) : la visibilité se
mesure avec `checkVisibility()`, pas avec `getClientRects()`.

Même banc que tests/test_texte_agrandi.py (Chromium piloté par le protocole DevTools, sauté s'il
est absent), sur un serveur à base vide propre au module.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
import uvicorn

from jobmail.web import app as web_app
from tests import test_texte_agrandi as banc

page = banc.page  # fixture Chromium du banc de texte agrandi


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    # Base vide à soi : d'autres modules repointent la base des réglages partagés.
    settings = web_app.get_settings()
    saved = settings.db_path
    settings.db_path = tmp_path_factory.mktemp("filtres") / "jobmail.db"
    port = banc._free_port()
    server = uvicorn.Server(
        uvicorn.Config(web_app.create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline, "le serveur de test ne démarre pas"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    settings.db_path = saved


def _resize(tab, width: int, height: int) -> None:
    tab.send(
        "Emulation.setDeviceMetricsOverride",
        width=width, height=height, deviceScaleFactor=1, mobile=False,
    )


def _open(tab, base_url: str, path: str, width: int, height: int) -> None:
    _resize(tab, width, height)
    tab.send("Page.setFontSizes", fontSizes={"standard": 16, "fixed": 13})
    tab.send("Page.navigate", url=base_url + path)
    tab.wait_for(
        f"location.href === {json.dumps(base_url + path)} && document.readyState === 'complete'"
    )
    tab.eval("document.fonts.ready.then(() => true)")


STATE = r"""
(() => {
  const fold = document.querySelector('[data-filters-fold]');
  const summary = fold.querySelector('summary');
  const s = summary.getBoundingClientRect();
  const texts = [...summary.querySelectorAll('span')].map((el) => parseFloat(getComputedStyle(el).fontSize));
  return {
    open: fold.open,
    summaryShown: summary.checkVisibility(),
    summaryHeight: s.height,
    summaryText: summary.textContent.replace(/\s+/g, ' ').trim(),
    minFont: Math.min(...texts),
    formShown: fold.querySelector('.filter-form').checkVisibility(),
    chipsShown: [...fold.querySelectorAll('.chip-link')].filter((el) => el.checkVisibility()).length,
    listTop: document.querySelector('.offers-wrap .section-header-title').getBoundingClientRect().top,
    afterFold: document.querySelector('.offers-wrap .section-header-title').getBoundingClientRect().top
      - fold.getBoundingClientRect().bottom,
    scrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
})()
"""


@pytest.mark.parametrize("width,height", [(320, 700), (390, 844), (844, 390)])
def test_replie_au_telephone_et_liste_dans_le_premier_ecran(page, base_url, width, height):
    _open(page, base_url, "/", width, height)
    m = page.eval(STATE)
    where = f"à {width} × {height}"
    assert m["summaryShown"], f"{where} : en-tête « Filtres » absent"
    assert not m["open"], f"{where} : filtres ouverts par défaut"
    assert not m["formShown"] and m["chipsShown"] == 0, f"{where} : champs encore visibles"
    assert m["summaryHeight"] >= 44, f"{where} : en-tête de {m['summaryHeight']} px"
    assert m["minFont"] >= 12, f"{where} : texte de {m['minFont']} px dans l'en-tête"
    assert m["summaryText"] == "Filtres aucun actif"
    # Rien entre l'en-tête « Filtres » et le titre de la liste, hors marges.
    assert m["afterFold"] <= 40, f"{where} : {m['afterFold']:.0f} px entre les filtres et la liste"
    if (width, height) == (390, 844):
        # Titre de la liste dans le premier écran (1 129 px avant).
        assert m["listTop"] < height, f"{where} : liste à {m['listTop']:.0f} px"
    assert m["scrollX"] <= 0, f"{where} : défile de {m['scrollX']} px en largeur"


@pytest.mark.parametrize("width,height", [(840, 900), (1440, 900)])
def test_ouvert_sans_en_tete_hors_telephone(page, base_url, width, height):
    _open(page, base_url, "/", width, height)
    m = page.eval(STATE)
    assert m["open"] and m["formShown"] and m["chipsShown"] == 7, f"à {width} px : filtres cachés"
    assert not m["summaryShown"], f"à {width} px : en-tête « Filtres » affiché"
    assert m["scrollX"] <= 0


@pytest.mark.parametrize("width", [320, 390])
def test_ouvert_au_toucher_tout_tient_dans_la_largeur(page, base_url, width):
    query = "/?status=new&since_days=7&min_score=5&esn=hide"
    _open(page, base_url, query, width, 800)
    m = page.eval(STATE)
    assert m["summaryText"] == "Filtres 4 actifs : Nouvelle, 7 derniers jours, score ≥ 5, sans ESN"
    assert m["summaryHeight"] >= 44 and m["minFont"] >= 12
    page.eval("document.querySelector('[data-filters-fold] summary').click()")
    m = page.eval(STATE)
    assert m["open"] and m["formShown"] and m["chipsShown"] == 7
    assert m["scrollX"] <= 0, f"à {width} px, filtres ouverts : défile de {m['scrollX']} px"
    small = page.eval(
        "[...document.querySelectorAll('[data-filters-fold] :is(select, input, .btn, .chip-link)')]"
        ".map((el) => [el.textContent.trim() || el.name, el.getBoundingClientRect().height])"
        ".filter(([, h]) => h < 44)"
    )
    assert small == [], f"à {width} px : cibles de moins de 44 px {small}"


def test_repasse_ouvert_quand_l_ecran_s_elargit(page, base_url):
    # Rotation ou fenêtre agrandie : hors téléphone, l'en-tête disparaît, le bloc doit s'ouvrir.
    _open(page, base_url, "/", 390, 844)
    assert not page.eval(STATE)["open"]
    _resize(page, 1440, 900)
    page.wait_for("document.querySelector('[data-filters-fold]').open")
    _resize(page, 390, 844)
    page.wait_for("!document.querySelector('[data-filters-fold]').open")


def test_le_bouton_de_l_etat_vide_lance_la_releve(page, base_url, monkeypatch):
    # Revue UX r1 : vrai clic, au lieu de chercher deux chaînes dans base.html. La relève elle-même
    # est remplacée par un faux travail qui note son lancement et reste en cours jusqu'à la fin.
    started, release = threading.Event(), threading.Event()

    def fake_run(settings, job):
        started.set()
        release.wait(timeout=30)
        job.status = "done"

    monkeypatch.setattr(web_app, "_run_refresh_job", fake_run)
    monkeypatch.setattr(web_app, "_refresh_job", None)
    _open(page, base_url, "/", 390, 844)
    try:
        page.eval("document.querySelector('.offers-empty button[form=\"refresh-form\"]').click()")
        assert started.wait(timeout=10), "le clic n'a lancé aucune relève"
        # Les deux boutons passent en cours, la ligne d'état de l'état vide suit la relève.
        page.wait_for(
            "[...document.querySelectorAll('button[form=\"refresh-form\"], #refresh-form button')]"
            ".every((b) => b.disabled && b.textContent.includes('Analyse'))"
            " && document.querySelector('.offers-empty [data-refresh-status]')"
            ".textContent.startsWith('Analyse Thunderbird')"
        )
    finally:
        release.set()
