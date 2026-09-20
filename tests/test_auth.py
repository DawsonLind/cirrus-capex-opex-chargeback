"""Unit tests for local .env loading and API key resolution."""

from __future__ import annotations

import os

import pytest

from src.auth import load_api_key, load_dotenv


def test_load_dotenv_sets_missing_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("CURSOR_API_KEY=from-file\nSMTP_HOST=smtp.example\n")

    load_dotenv(env_file)

    assert os.environ["CURSOR_API_KEY"] == "from-file"
    assert os.environ["SMTP_HOST"] == "smtp.example"


def test_load_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "from-env")
    env_file = tmp_path / ".env"
    env_file.write_text("CURSOR_API_KEY=from-file\n")

    load_dotenv(env_file)

    assert os.environ["CURSOR_API_KEY"] == "from-env"


def test_load_api_key_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "env-key")
    secrets = tmp_path / "box-secrets.json"
    secrets.write_text('{"card": {"CURSOR_API_KEY": "file-key"}}')

    assert load_api_key(secrets) == "env-key"


def test_load_api_key_falls_back_to_secrets_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    secrets = tmp_path / "box-secrets.json"
    secrets.write_text('{"card": {"CURSOR_API_KEY": "file-key"}}')

    assert load_api_key(secrets) == "file-key"


def test_load_api_key_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    missing = tmp_path / "does-not-exist.json"

    with pytest.raises(RuntimeError, match="CURSOR_API_KEY"):
        load_api_key(missing)
