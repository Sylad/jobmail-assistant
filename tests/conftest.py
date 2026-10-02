from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Garde-fou vie privée : `jobmail.web.app` crée son application à l'import
# (`app = create_app()`), donc ouvre la base de `get_settings()` dès la collecte des
# tests. Sans ces variables, ce serait la vraie base (./data/jobmail.db, lue via .env).
# Les variables d'environnement passent avant le fichier .env (pydantic-settings) :
# toute la suite tourne sur un dossier temporaire, sans boîte aux lettres réelle.
_ISOLATED = Path(tempfile.mkdtemp(prefix="jobmail-tests-"))
os.environ["DB_PATH"] = str(_ISOLATED / "jobmail.db")
os.environ["CLEANER_REGEX_RULES_PATH"] = str(_ISOLATED / "cleaner-regex-rules.json")
os.environ["CLEANER_MBOX_GLOBS"] = str(_ISOLATED / "no-thunderbird" / "Inbox")
os.environ["IMAP_HOST"] = ""
os.environ["IMAP_USER"] = ""
os.environ["IMAP_PASSWORD"] = ""
os.environ["LLM_PROVIDER"] = "mock"

ISOLATED_DATA_DIR = _ISOLATED


@pytest.fixture
def tmp_settings(tmp_path):
    from jobmail.config import Settings

    return Settings(
        db_path=tmp_path / "test.db",
        llm_provider="mock",
        imap_host="",  # disable IMAP
        target_profile="Java senior GeoServer OpenLayers Kubernetes",
    )
