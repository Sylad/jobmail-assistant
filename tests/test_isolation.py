"""La suite ne touche jamais la vraie base : l'application créée à l'import pointe
sur le dossier temporaire posé par conftest.py."""
from __future__ import annotations

from pathlib import Path

from tests.conftest import ISOLATED_DATA_DIR

REPO = Path(__file__).resolve().parents[1]


def test_web_app_import_uses_isolated_database():
    from jobmail.web import app as web_app

    settings = web_app.get_settings()
    db = Path(settings.db_path).resolve()
    # Les tests web peuvent re-pointer la base sur leur tmp_path : jamais sur le dépôt.
    assert REPO not in db.parents
    assert ISOLATED_DATA_DIR.is_dir()
