from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_fetch_limit: int = 50

    cleaner_min_age_days: int = 7
    cleaner_max_mails: int = 250
    cleaner_delete_folder: str = "ToDelete"
    cleaner_mbox_globs: str = (
        "/mnt/c/Users/Sylvain Ladoire/AppData/Roaming/Thunderbird/Profiles/"
        "*.default*/Mail/pop.*/Inbox"
    )
    cleaner_regex_rules_path: Path = Path("./data/cleaner-regex-rules.json")
    cleaner_backup_retention_days: int = 7

    db_path: Path = Path("./data/jobmail.db")

    llm_provider: Literal["mock", "ollama", "claude", "openai"] = "mock"
    dry_run: bool = False

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    target_profile: str = Field(
        default="Java senior, GeoServer, OpenLayers, Kubernetes, PostGIS, Spring, Docker"
    )

    web_host: str = "127.0.0.1"
    web_port: int = 8765

    @property
    def imap_enabled(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)

    @property
    def cleaner_mbox_patterns(self) -> list[str]:
        return [part.strip() for part in self.cleaner_mbox_globs.split(",") if part.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
