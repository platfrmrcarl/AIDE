import importlib
import shutil

SUPPORTED_PROVIDERS = {
    "anthropic": {
        "default_model": "claude-opus-4-7",
        "api_key_env": "ANTHROPIC_API_KEY",
        "supports_subscription": True,
        "default_cli_cmd": "claude",
    },
    "openai": {
        "default_model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
        "supports_subscription": False,
        "default_cli_cmd": None,
    },
    "google": {
        "default_model": "gemini-2.0-flash",
        "api_key_env": "GEMINI_API_KEY",
        "supports_subscription": True,
        "default_cli_cmd": "gemini",
    },
    "perplexity": {
        "default_model": "sonar-pro",
        "api_key_env": "PERPLEXITY_API_KEY",
        "supports_subscription": False,
        "default_cli_cmd": None,
    },
}

WORKER_CLI_PRIORITY = ["claude", "codex", "gemini"]


def get_provider(name: str):
    if name not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return importlib.import_module(f".{name}", package="aide.providers")


def detect_worker_cmd() -> str | None:
    for cmd in WORKER_CLI_PRIORITY:
        if shutil.which(cmd):
            return cmd
    return None


def resolve_auth_mode(
    auth_mode: str,
    api_key: str | None,
    supports_subscription: bool,
    provider_name: str,
) -> str:
    if auth_mode == "subscription":
        if not supports_subscription:
            raise ValueError(
                f"{provider_name} does not support subscription mode — use auth_mode: api_key"
            )
        return "subscription"
    if auth_mode == "api_key":
        return "api_key"
    # auto
    if api_key:
        return "api_key"
    if supports_subscription:
        return "subscription"
    raise ValueError(
        f"{provider_name} requires an API key. "
        f"Set {SUPPORTED_PROVIDERS[provider_name]['api_key_env']} or use auth_mode: api_key"
    )
