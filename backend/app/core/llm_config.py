"""Central resolution of the LLM provider/model configuration.

The whole LLM layer is OpenAI-shaped (an ``OPENAI_BASE_URL`` override plus
``response_format={"type": "json_object"}``), so a single set of environment
variables selects the provider:

    OPENAI_BASE_URL         OpenAI-compatible endpoint
    OPENAI_API_KEY          credential (not required for local runtimes)
    OPENAI_MODEL            primary model id
    OPENAI_FALLBACK_MODEL   fallback model id

Two approved profiles are supported (see docs/LOCAL_LLM.md and
docs/DECISIONS.md):

* Cloud  - Google Gemini via its OpenAI-compatible endpoint
           (primary ``gemini-2.5-flash`` / fallback ``gemini-3.5-flash``).
* Local  - Ollama's OpenAI-compatible endpoint on ``localhost:11434``
           (e.g. primary/fallback ``llama3.1``).

This module is the one place that knows how to detect a local runtime, supply a
placeholder credential for it, and produce the provider label recorded into
every evaluation dump, so provenance stays consistent across the agents, the
orchestrator, and ``run_pipeline.py``.
"""

import os

# Substrings that identify a locally-hosted OpenAI-compatible runtime
# (Ollama, LM Studio, llama.cpp server, vLLM on localhost, ...).
_LOCAL_HINTS = ("localhost", "127.0.0.1", "0.0.0.0", ":11434", "ollama")

# Local runtimes accept any (or no) bearer token; the OpenAI client still
# requires a non-empty string, so we supply this placeholder when the user has
# not set OPENAI_API_KEY and is pointing at a local endpoint.
_LOCAL_PLACEHOLDER_KEY = "ollama-local"


def base_url() -> str:
    """Return the configured OpenAI-compatible base URL ("" if unset)."""
    return os.getenv("OPENAI_BASE_URL", "") or ""


def is_local_endpoint(url: str | None = None) -> bool:
    """True when the base URL points at a locally-hosted LLM runtime."""
    candidate = (url if url is not None else base_url()).lower()
    return any(hint in candidate for hint in _LOCAL_HINTS)


def api_key() -> str | None:
    """Resolve the credential, injecting a placeholder for local runtimes."""
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    return _LOCAL_PLACEHOLDER_KEY if is_local_endpoint() else None


def is_configured() -> bool:
    """True when an LLM call can be made: a key is set, or the endpoint is local."""
    return bool(os.getenv("OPENAI_API_KEY")) or is_local_endpoint()


def primary_model() -> str:
    return os.getenv("OPENAI_MODEL", "gemini-2.5-flash")


def fallback_model() -> str:
    return os.getenv("OPENAI_FALLBACK_MODEL", "gemini-3.5-flash")


def provider_label(url: str | None = None) -> str:
    """Human-readable provider name for a base URL, recorded in eval dumps."""
    low = (url if url is not None else base_url()).lower()
    if is_local_endpoint(low):
        return "ollama-local (openai-compatible)"
    if "generativelanguage.googleapis.com" in low:
        return "google-gemini (openai-compatible)"
    if "groq.com" in low:
        return "groq (openai-compatible)"
    if low:
        return low
    return "openai"


def client_kwargs() -> dict:
    """Keyword args for constructing an OpenAI-compatible client."""
    return {"api_key": api_key(), "base_url": base_url() or None}


def run_config() -> dict:
    """The provider/model configuration actually in effect, for eval provenance."""
    return {
        "provider": provider_label(),
        "base_url": base_url(),
        "primary_model": primary_model(),
        "fallback_model": fallback_model(),
    }


# Message reused by the callers' "no LLM configured" guards.
NOT_CONFIGURED_MESSAGE = (
    "No LLM configured. Set OPENAI_API_KEY for a cloud provider, or point "
    "OPENAI_BASE_URL at a local runtime (e.g. Ollama). See docs/LOCAL_LLM.md."
)
