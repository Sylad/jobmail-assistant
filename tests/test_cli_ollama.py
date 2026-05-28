from __future__ import annotations

from pathlib import Path

from jobmail.cli import _ensure_ollama_started, _ollama_host, _resolve_ollama_binary
from jobmail.config import Settings


def test_ollama_host_from_base_url():
    assert _ollama_host("http://127.0.0.1:11434") == "127.0.0.1:11434"
    assert _ollama_host("localhost:11434") == "localhost:11434"


def test_resolve_ollama_binary_prefers_setting(tmp_path: Path):
    binary = tmp_path / "ollama"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    settings = Settings(ollama_binary=str(binary))

    assert _resolve_ollama_binary(settings) == str(binary)


def test_ensure_ollama_started_skips_non_ollama(monkeypatch):
    calls = []
    settings = Settings(llm_provider="mock")

    monkeypatch.setattr("jobmail.cli._provider_available", lambda _settings: calls.append("check"))

    _ensure_ollama_started(settings)

    assert calls == []


def test_ensure_ollama_started_launches_when_unreachable(monkeypatch, tmp_path: Path):
    binary = tmp_path / "ollama"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    settings = Settings(llm_provider="ollama", ollama_binary=str(binary))
    availability = iter([False, False, True])
    popen_calls = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            popen_calls.append((args, kwargs))

    monkeypatch.setattr("jobmail.cli._provider_available", lambda _settings: next(availability))
    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _ensure_ollama_started(settings)

    assert popen_calls
    args, kwargs = popen_calls[0]
    assert args[0] == [str(binary), "serve"]
    assert kwargs["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert kwargs["start_new_session"] is True
