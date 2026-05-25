from __future__ import annotations

import pytest

from jobmail.config import Settings


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        db_path=tmp_path / "test.db",
        llm_provider="mock",
        imap_host="",  # disable IMAP
        target_profile="Java senior GeoServer OpenLayers Kubernetes",
    )
