from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ── Garde-fou vie privée (exécuté avant l'import de tout module de test) ───────────
#
# `jobmail.web.app` crée son application à l'import (`app = create_app()`), donc ouvre
# la base de `get_settings()` dès la collecte. Et `Settings` lit le fichier `.env` du
# dossier courant (clés d'API, profil…). Pour toute la suite :
#   1. aucun fichier .env n'est lu (importer jobmail.config n'ouvre aucun fichier ; seule
#      l'instanciation de Settings lit .env, d'où la désactivation avant toute instance) ;
#   2. aucune variable d'environnement du shell ne nourrit Settings, sauf les nôtres ;
#   3. base, règles regex et MBOX pointent vers un dossier temporaire, IMAP vide ;
#   4. si l'un de ces points visait malgré tout data/ du dépôt ou /mnt/c, la session
#      s'arrête AVANT l'import de l'application.
from jobmail import config as _config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
REAL_DATA = REPO / "data"

_config.Settings.model_config["env_file"] = None

_ISOLATED = Path(tempfile.mkdtemp(prefix="jobmail-tests-"))
ISOLATED_DATA_DIR = _ISOLATED
OVERRIDES = {
    "DB_PATH": str(_ISOLATED / "jobmail.db"),
    "CLEANER_REGEX_RULES_PATH": str(_ISOLATED / "cleaner-regex-rules.json"),
    "CLEANER_MBOX_GLOBS": str(_ISOLATED / "no-thunderbird" / "Inbox"),
    "IMAP_HOST": "",
    "IMAP_USER": "",
    "IMAP_PASSWORD": "",
    "LLM_PROVIDER": "mock",
}
_FIELDS = {name.upper() for name in _config.Settings.model_fields}
for _name in list(os.environ):
    if _name.upper() in _FIELDS and _name.upper() not in OVERRIDES:
        del os.environ[_name]
os.environ.update(OVERRIDES)


def points_at_real_data(value: object) -> bool:
    """Vrai si un chemin (ou motif glob) vise data/ du dépôt ou le disque Windows."""
    text = str(value)
    if text.startswith("/mnt/c") or "/mnt/c/" in text:
        return True
    try:
        resolved = Path(text).expanduser().resolve()
    except (OSError, RuntimeError):
        return True
    return resolved == REAL_DATA or REAL_DATA in resolved.parents


def isolation_problems(settings) -> list[str]:
    problems = []
    if _config.Settings.model_config.get("env_file") is not None:
        problems.append("un fichier .env est configuré")
    for label, value in (
        ("db_path", settings.db_path),
        ("cleaner_regex_rules_path", settings.cleaner_regex_rules_path),
        *(("cleaner_mbox_globs", g) for g in settings.cleaner_mbox_patterns),
    ):
        if points_at_real_data(value) or _ISOLATED not in Path(str(value)).parents:
            problems.append(f"{label} hors du dossier temporaire")
    if settings.imap_host or settings.imap_user or settings.imap_password:
        problems.append("IMAP configuré")
    return problems


_problems = isolation_problems(_config.Settings())
if _problems:
    pytest.exit("Isolation des tests rompue : " + " ; ".join(_problems), returncode=3)


@pytest.fixture
def tmp_settings(tmp_path):
    from jobmail.config import Settings

    return Settings(
        db_path=tmp_path / "test.db",
        llm_provider="mock",
        imap_host="",  # disable IMAP
        target_profile="Java senior GeoServer OpenLayers Kubernetes",
    )
