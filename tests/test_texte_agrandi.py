"""L8 — texte agrandi (WCAG 1.4.4) et petit écran (WCAG 1.4.10), mesurés dans Chromium.

La taille de police choisie dans le navigateur est émulée par le protocole DevTools
(`Page.setFontSizes`, 16 px par défaut ; 20 px, et 32 px = 200 %) et la largeur de l'écran par
`Emulation.setDeviceMetricsOverride`. Sur l'application de test (base vide, conftest.py), chaque
élément nommé par la revue UX doit tenir entier dans l'écran et dans tout ancêtre qui masque son
débordement, sans texte coupé dans sa propre boîte ; la page ne défile pas en largeur.

Sauté si aucun Chromium n'est trouvé (variable CHROME_BIN, chrome/chromium du PATH, ou celui de
Playwright dans ~/.cache/ms-playwright). La CI GitHub (ubuntu-latest) a google-chrome.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn
from websockets.sync.client import connect

from jobmail.web import app as web_app


def _chrome() -> str | None:
    if os.environ.get("CHROME_BIN"):
        return os.environ["CHROME_BIN"]
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    for name in names:
        if found := shutil.which(name):
            return found
    cache = Path.home() / ".cache" / "ms-playwright"
    found = sorted(cache.glob("chromium-*/chrome-linux*/chrome"), reverse=True)
    return str(found[0]) if found else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
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


class _Page:
    """Un onglet Chromium piloté par le protocole DevTools (une commande à la fois)."""

    def __init__(self, ws_url: str):
        self._ws = connect(ws_url, max_size=None, open_timeout=15)
        self._ids = itertools.count(1)

    def send(self, method: str, **params):
        msg_id = next(self._ids)
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self._ws.recv(timeout=30))
            if msg.get("id") == msg_id:
                assert "error" not in msg, (method, msg["error"])
                return msg.get("result", {})

    def eval(self, expression: str):
        result = self.send(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        assert "exceptionDetails" not in result, result["exceptionDetails"]
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while not self.eval(expression):
            assert time.monotonic() < deadline, f"attente trop longue : {expression}"
            time.sleep(0.05)

    def close(self):
        self._ws.close()


@pytest.fixture(scope="module")
def page():
    chrome = _chrome()
    if chrome is None:
        pytest.skip("Chromium absent : mesures du texte agrandi non lancées")
    profile = tempfile.mkdtemp(prefix="jobmail-chrome-")
    proc = subprocess.Popen(
        [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
            "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        port_file = Path(profile) / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not (port_file.exists() and port_file.read_text().strip()):
            if proc.poll() is not None:  # ex. bibliothèque système manquante (libasound.so.2)
                pytest.skip(f"{chrome} ne démarre pas : {proc.stderr.read().decode()[-300:]}")
            assert time.monotonic() < deadline, "Chromium ne répond pas"
            time.sleep(0.05)
        port = port_file.read_text().split()[0]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as resp:
            target = next(t for t in json.load(resp) if t["type"] == "page")
        tab = _Page(target["webSocketDebuggerUrl"])
        tab.send("Page.enable")
        yield tab
        tab.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


# Débordement des éléments d'un sélecteur : ce qui sort de l'écran, de leur propre boîte (texte
# coupé) ou d'un ancêtre qui masque ou fait défiler son contenu (texte rogné). En px, 0 si tout tient.
MEASURE = r"""
((selector) => {
  const els = [...document.querySelectorAll(selector)].filter((el) => el.getClientRects().length);
  if (!els.length) return {missing: true};
  let worst = 0, where = "";
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const what = JSON.stringify(el.textContent.trim().replace(/\s+/g, " ").slice(0, 40));
    const out = (amount, label) => { if (amount > worst) { worst = amount; where = what + " : " + label; } };
    out(r.right - document.documentElement.clientWidth, "hors de l'écran");
    out(-r.left, "hors de l'écran à gauche");
    out(el.scrollWidth - el.clientWidth, "texte coupé dans sa boîte");
    for (let a = el.parentElement; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX === "visible" && s.overflowY === "visible") continue;
      const ar = a.getBoundingClientRect();
      const label = "rogné par " + (a.id ? "#" + a.id : "." + a.classList[0] || a.tagName);
      out(r.right - ar.right, label);
      out(ar.left - r.left, label);
      out(r.bottom - ar.bottom, label + " (en bas)");
    }
  }
  return {worst: Math.round(worst * 10) / 10, where};
})
"""

ELEMENTS = [
    ("/", "#reanalyze-start", "« Ré-analyser avec Ollama »"),
    ("/", ".kpi-label", "étiquettes KPI"),
    ("/", ".kpi-tag", "pastilles KPI"),
    ("/", ".chip-link", "raccourcis (« Nouvelles uniquement »)"),
    ("/cleaner", ".backup-action-slot .btn-danger", "« Nettoyer les anciens backups »"),
    ("/cleaner", ".backup-details > summary > span", "résumé « 0 backup(s), 0 B »"),
    ("/nouveautes", ".news-copy", "« Copier le lien »"),
]
# (largeur de l'écran, taille de police du navigateur), mesures de la revue UX : 300 px police 20,
# 320 px (seuil de WCAG 1.4.10) et 390 px police 32 (200 %).
CASES = [(300, 20), (320, 32), (390, 32)]


def _open(page: _Page, base_url: str, path: str, width: int, font: int) -> None:
    page.send(
        "Emulation.setDeviceMetricsOverride",
        width=width, height=800, deviceScaleFactor=1, mobile=False,
    )
    page.send("Page.setFontSizes", fontSizes={"standard": font, "fixed": round(font * 13 / 16)})
    page.send("Page.navigate", url=base_url + path)
    page.wait_for(f"location.pathname === {json.dumps(path)} && document.readyState === 'complete'")
    page.eval("document.fonts.ready.then(() => true)")
    # Le panneau des backups est replié par défaut : on l'ouvre pour mesurer son bouton.
    page.eval("document.querySelectorAll('details.backup-details').forEach(d => d.open = true)")


@pytest.mark.parametrize("width,font", CASES)
@pytest.mark.parametrize("path,selector,label", ELEMENTS)
def test_libelle_entier_quand_le_texte_grandit(page, base_url, path, selector, label, width, font):
    _open(page, base_url, path, width, font)
    found = page.eval(f"{MEASURE}({json.dumps(selector)})")
    assert not found.get("missing"), f"{label} absent de {path}"
    assert found["worst"] <= 0.5, (
        f"{label} sur {path} à {width} px, police {font} px : "
        f"{found['worst']} px dépassent ({found['where']})"
    )


@pytest.mark.parametrize("width,font", [(300, 16), *CASES])
@pytest.mark.parametrize("path", ["/", "/cleaner", "/nouveautes", "/plan-de-travail"])
def test_aucun_defilement_horizontal(page, base_url, path, width, font):
    _open(page, base_url, path, width, font)
    extra = page.eval(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert extra <= 0, f"{path} à {width} px, police {font} px : défile de {extra} px en largeur"


def test_la_police_emulee_agrandit_bien_le_texte(page, base_url):
    # Garde-fou de la mesure : si Page.setFontSizes restait sans effet, tout passerait.
    _open(page, base_url, "/", 390, 32)
    assert page.eval("parseFloat(getComputedStyle(document.documentElement).fontSize)") == 32


# L20 — pastille Nouveautés : le chiffre reste entier dans sa pastille quand le texte grandit.
# Elle est allumée avec « 9+ » (le texte le plus large qu'elle affiche) sur le lien visible
# (barre latérale sur ordinateur, barre du bas au téléphone), puis on compare la boîte du texte
# (Range) à celle de la pastille, dans les deux sens.
BADGE = r"""
(() => {
  const b = [...document.querySelectorAll('[data-news-badge]')]
    .find((el) => el.closest('a').getClientRects().length);
  b.classList.add('is-on');
  b.textContent = '9+';
  const box = b.getBoundingClientRect();
  const range = document.createRange();
  range.selectNodeContents(b);
  const text = range.getBoundingClientRect();
  return {
    height: box.height,
    fontSize: parseFloat(getComputedStyle(b).fontSize),
    over: Math.max(box.top - text.top, text.bottom - box.bottom,
                   box.left - text.left, text.right - box.right),
  };
})()
"""


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("font", [16, 32])
def test_pastille_nouveautes_contient_son_chiffre(page, base_url, width, font):
    _open(page, base_url, "/", width, font)
    badge = page.eval(BADGE)
    # L19/t1 : chiffre à 12 px (11 avant), pastille de 1,5455 em, soit 18,5 px (17 avant).
    assert badge["fontSize"] == pytest.approx(12 * font / 16), "la police émulée n'a pas pris"
    assert badge["over"] <= 0, (
        f"pastille à {width} px, police {font} px : le chiffre dépasse de {badge['over']} px"
    )
    # La pastille grandit avec le texte.
    assert badge["height"] == pytest.approx(18.5 * font / 16, abs=0.5)


# L21 — barre latérale (ordinateur, 1024 à 1440 px) : la pastille allumée « 9+ » ne recouvre
# jamais le libellé « Nouveautés ». Le libellé garde sa taille de police (non rétréci) et son
# texte reste entier dans le lien et dans la barre latérale (non masqué). La boîte du texte
# (Range) est comparée à celle de la pastille : leur intersection doit être vide.
SIDEBAR_BADGE = r"""
(() => {
  const link = document.querySelector('.sidebar [data-news-link]');
  const label = link.querySelector('.nav-label');
  const b = link.querySelector('[data-news-badge]');
  b.classList.add('is-on');
  b.textContent = '9+';
  const range = document.createRange();
  range.selectNodeContents(label);
  const t = range.getBoundingClientRect();
  const p = b.getBoundingClientRect();
  const l = link.getBoundingClientRect();
  const s = document.querySelector('.sidebar').getBoundingClientRect();
  const nav = document.querySelector('.sidebar-nav').getBoundingClientRect();
  return {
    visible: !!link.getClientRects().length,
    overlapX: Math.min(t.right, p.right) - Math.max(t.left, p.left),
    overlapY: Math.min(t.bottom, p.bottom) - Math.max(t.top, p.top),
    labelFont: parseFloat(getComputedStyle(label).fontSize),
    rootFont: parseFloat(getComputedStyle(document.documentElement).fontSize),
    labelClipped: label.scrollWidth - label.clientWidth,
    outside: Math.max(t.right - l.right, l.left - t.left, p.right - l.right,
                      p.bottom - l.bottom, t.right - nav.right, p.right - s.right),
  };
})()
"""


@pytest.mark.parametrize("width", [1024, 1280, 1440])
@pytest.mark.parametrize("font", [16, 32])
def test_pastille_ne_recouvre_pas_le_libelle_nouveautes(page, base_url, width, font):
    _open(page, base_url, "/", width, font)
    m = page.eval(SIDEBAR_BADGE)
    assert m["visible"], f"barre latérale absente à {width} px"
    assert m["rootFont"] == font, "la police émulée n'a pas pris"
    where = f"à {width} px, police {font} px"
    assert not (m["overlapX"] > 0 and m["overlapY"] > 0), (
        f"{where} : la pastille recouvre le libellé Nouveautés "
        f"({m['overlapX']:.0f} × {m['overlapY']:.0f} px)"
    )
    # Non rétréci : 13,5 px à 16 px de police (0.84375rem), proportionnel au texte agrandi.
    assert m["labelFont"] == pytest.approx(13.5 * font / 16), "libellé rétréci"
    # Non masqué : le texte tient dans sa boîte, dans le lien et dans la barre latérale.
    assert m["labelClipped"] <= 0, f"{where} : libellé coupé de {m['labelClipped']} px"
    assert m["outside"] <= 0.5, f"{where} : libellé ou pastille déborde de {m['outside']:.1f} px"
