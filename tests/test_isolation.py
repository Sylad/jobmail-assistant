"""La suite ne touche jamais les vraies données : ni .env, ni data/ du dépôt, ni le profil
Thunderbird. Contrôle sur os.environ et sur un Settings() NEUF (l'objet partagé de
l'application est modifié par d'autres tests, il ne prouverait rien)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jobmail import config
from tests.conftest import (
    ISOLATED_DATA_DIR,
    OVERRIDES,
    REAL_DATA,
    isolation_problems,
    points_at_real_data,
)


def _under_tmp(value: object) -> bool:
    return ISOLATED_DATA_DIR in Path(str(value)).parents


def test_no_env_file_is_configured():
    assert config.Settings.model_config.get("env_file") is None


def test_environment_points_only_at_the_temporary_folder():
    for name in ("DB_PATH", "CLEANER_REGEX_RULES_PATH", "CLEANER_MBOX_GLOBS"):
        assert _under_tmp(os.environ[name]), name
        assert not points_at_real_data(os.environ[name]), name
    for name in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        assert os.environ[name] == "", name


def test_fresh_settings_hold_only_defaults_and_overrides():
    fresh = config.Settings()
    assert isolation_problems(fresh) == []
    assert _under_tmp(fresh.db_path)
    assert _under_tmp(fresh.cleaner_regex_rules_path)
    assert all(_under_tmp(g) for g in fresh.cleaner_mbox_patterns)
    assert not fresh.imap_enabled
    overridden = {name.lower() for name in OVERRIDES}
    for name, field in config.Settings.model_fields.items():
        if name not in overridden:
            assert getattr(fresh, name) == field.get_default(call_default_factory=True), name


@pytest.mark.parametrize(
    ("value", "real"),
    [
        (REAL_DATA / "jobmail.db", True),
        (REAL_DATA, True),
        ("/mnt/c/Users/x/AppData/Roaming/Thunderbird/Profiles/*/Mail/pop.*/Inbox", True),
        (ISOLATED_DATA_DIR / "jobmail.db", False),
    ],
)
def test_safety_net_recognises_real_data(value, real):
    assert points_at_real_data(value) is real
