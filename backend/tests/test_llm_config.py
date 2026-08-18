"""Unit tests for the central LLM provider/model resolver (app/core/llm_config).

Covers the local (Ollama) vs cloud (Gemini) profile selection that satisfies the
Option-D "local and cloud LLM" requirement, and the provenance label recorded
into evaluation dumps.
"""

import pytest

from app.core import llm_config


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_FALLBACK_MODEL"):
        monkeypatch.delenv(var, raising=False)


def _use_local(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("OPENAI_MODEL", "llama3.1")
    monkeypatch.setenv("OPENAI_FALLBACK_MODEL", "llama3.1")


def _use_cloud(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "real-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:11434/v1", True),
        ("http://0.0.0.0:11434/v1", True),
        ("https://generativelanguage.googleapis.com/v1beta/openai/", False),
        ("https://api.groq.com/openai/v1", False),
        ("", False),
    ],
)
def test_is_local_endpoint(url, expected):
    assert llm_config.is_local_endpoint(url) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:11434/v1", "ollama-local (openai-compatible)"),
        ("https://generativelanguage.googleapis.com/v1beta/openai/", "google-gemini (openai-compatible)"),
        ("https://api.groq.com/openai/v1", "groq (openai-compatible)"),
        ("", "openai"),
    ],
)
def test_provider_label(url, expected):
    assert llm_config.provider_label(url) == expected


def test_local_supplies_placeholder_key_and_is_configured(monkeypatch):
    _use_local(monkeypatch)
    assert llm_config.is_configured() is True
    assert llm_config.api_key() == "ollama-local"
    assert llm_config.client_kwargs() == {
        "api_key": "ollama-local",
        "base_url": "http://localhost:11434/v1",
    }


def test_explicit_key_wins_even_for_local(monkeypatch):
    _use_local(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "ollama")
    assert llm_config.api_key() == "ollama"


def test_cloud_requires_key(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    assert llm_config.is_configured() is False  # no key, non-local endpoint
    assert llm_config.api_key() is None


def test_run_config_records_local_profile(monkeypatch):
    _use_local(monkeypatch)
    cfg = llm_config.run_config()
    assert cfg == {
        "provider": "ollama-local (openai-compatible)",
        "base_url": "http://localhost:11434/v1",
        "primary_model": "llama3.1",
        "fallback_model": "llama3.1",
    }


def test_run_config_records_cloud_defaults(monkeypatch):
    _use_cloud(monkeypatch)
    cfg = llm_config.run_config()
    assert cfg["provider"] == "google-gemini (openai-compatible)"
    assert cfg["primary_model"] == "gemini-2.5-flash"
    assert cfg["fallback_model"] == "gemini-3.5-flash"
