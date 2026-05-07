import shutil
import pytest
from unittest.mock import patch
from aide.providers import (
    SUPPORTED_PROVIDERS,
    WORKER_CLI_PRIORITY,
    detect_worker_cmd,
    get_provider,
    resolve_auth_mode,
)


def test_supported_providers_keys():
    assert set(SUPPORTED_PROVIDERS.keys()) == {"anthropic", "openai", "google", "perplexity"}


def test_supported_providers_fields():
    for name, meta in SUPPORTED_PROVIDERS.items():
        assert "default_model" in meta
        assert "api_key_env" in meta
        assert "supports_subscription" in meta
        assert "default_cli_cmd" in meta


def test_worker_cli_priority_order():
    assert WORKER_CLI_PRIORITY == ["claude", "codex", "gemini"]


def test_detect_worker_cmd_returns_first_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude" if cmd == "claude" else None)
    assert detect_worker_cmd() == "claude"


def test_detect_worker_cmd_returns_second_if_first_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/codex" if cmd == "codex" else None)
    assert detect_worker_cmd() == "codex"


def test_detect_worker_cmd_returns_none_if_none_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert detect_worker_cmd() is None


def test_get_provider_anthropic():
    mod = get_provider("anthropic")
    assert hasattr(mod, "generate")


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("fakeprovider")


def test_resolve_auth_mode_api_key():
    assert resolve_auth_mode("api_key", "key123", True, "anthropic") == "api_key"


def test_resolve_auth_mode_subscription_supported():
    assert resolve_auth_mode("subscription", None, True, "anthropic") == "subscription"


def test_resolve_auth_mode_subscription_unsupported_raises():
    with pytest.raises(ValueError, match="does not support subscription"):
        resolve_auth_mode("subscription", None, False, "openai")


def test_resolve_auth_mode_auto_uses_api_key_when_available():
    assert resolve_auth_mode("auto", "key123", True, "anthropic") == "api_key"


def test_resolve_auth_mode_auto_falls_back_to_subscription():
    assert resolve_auth_mode("auto", None, True, "anthropic") == "subscription"


def test_resolve_auth_mode_auto_no_subscription_no_key_raises():
    with pytest.raises(ValueError, match="requires an API key"):
        resolve_auth_mode("auto", None, False, "perplexity")
