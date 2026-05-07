# AIDE LLM-Agnostic Provider Design Spec

**Date:** 2026-05-07
**Status:** Approved
**Repo:** platfrmrcarl/AIDE

---

## Overview

Replace AIDE's hard-wired Anthropic/Claude dependency with a thin provider adapter layer. Users can configure any supported LLM for task planning (Anthropic, OpenAI, Google, Perplexity) using either an API key or a subscription CLI. Worker execution auto-detects the best available agentic CLI regardless of which provider handles planning.

---

## Goals

1. Support 4 planning providers: Anthropic, OpenAI, Google, Perplexity
2. Each provider supports `auth_mode: "api_key"` (SDK); Anthropic and Google also support `auth_mode: "subscription"` (CLI subprocess)
3. `auth_mode: "auto"` (default) — use API key if env var set, else fall back to subscription CLI
4. Worker execution auto-detects installed CLI: `claude` → `codex` → `gemini` (configurable override)
5. `aide init` gains interactive provider setup; `--no-interactive` for CI
6. OpenAI and Perplexity raise a clear error if `subscription` mode is requested

---

## Non-Goals

- Streaming responses from providers
- Provider-specific advanced parameters (temperature, top-p)
- Supporting more than 4 providers in this iteration

---

## Architecture

```
aide/
  providers/
    __init__.py      # get_provider(name), detect_worker_cmd(), SUPPORTED_PROVIDERS
    anthropic.py     # generate() — api_key: SDK, subscription: claude --print
    openai.py        # generate() — api_key: OpenAI SDK only
    google.py        # generate() — api_key: google-generativeai SDK, subscription: gemini --print
    perplexity.py    # generate() — api_key: httpx POST to api.perplexity.ai only
  planner.py         # calls providers.get_provider(name).generate(...)
  worker.py          # resolves worker_cmd via detect_worker_cmd() when "auto"
  workspace.py       # updated default config schema
  cli.py             # aide init gains --no-interactive + provider prompts
```

---

## Provider Interface

Every provider module exposes exactly one public function:

```python
def generate(
    prompt: str,
    model: str,
    api_key: str | None,
    auth_mode: str,          # "api_key" | "subscription" | "auto"
    cli_cmd: str = "claude", # used only when auth_mode resolves to subscription
) -> str:
    """Call the LLM and return the raw text response."""
```

Rules:
- If `auth_mode == "subscription"` and provider does not support it → raise `ValueError("openai does not support subscription mode — use auth_mode: api_key")`
- If `auth_mode == "auto"` → use API key if `api_key` is not None/empty, else try subscription CLI
- All providers strip and return plain text (no JSON wrapping at this layer)

---

## Provider Catalogue

### `aide/providers/anthropic.py`

| auth_mode | mechanism |
|-----------|-----------|
| `api_key` | `anthropic.Anthropic(api_key=api_key).messages.create(...)` |
| `subscription` | `subprocess: [cli_cmd, "--print", prompt]` |

Default model: `claude-opus-4-7`
Default api_key_env: `ANTHROPIC_API_KEY`
Default cli_cmd: `claude`

### `aide/providers/openai.py`

| auth_mode | mechanism |
|-----------|-----------|
| `api_key` | `openai.OpenAI(api_key=api_key).chat.completions.create(...)` |
| `subscription` | raises `ValueError` |

Default model: `gpt-4o`
Default api_key_env: `OPENAI_API_KEY`

### `aide/providers/google.py`

| auth_mode | mechanism |
|-----------|-----------|
| `api_key` | `google.generativeai.GenerativeModel(model).generate_content(...)` |
| `subscription` | `subprocess: [cli_cmd, "--print", prompt]` |

Default model: `gemini-2.0-flash`
Default api_key_env: `GEMINI_API_KEY`
Default cli_cmd: `gemini`

### `aide/providers/perplexity.py`

| auth_mode | mechanism |
|-----------|-----------|
| `api_key` | `httpx.post("https://api.perplexity.ai/chat/completions", ...)` |
| `subscription` | raises `ValueError` |

Default model: `sonar-pro`
Default api_key_env: `PERPLEXITY_API_KEY`

---

## `aide/providers/__init__.py`

```python
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
    """Return the provider module for the given name."""

def detect_worker_cmd() -> str | None:
    """Return first available worker CLI from WORKER_CLI_PRIORITY, or None."""
```

---

## Config Schema

`.aide/config.json` after this change:

```json
{
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "auth_mode": "auto",
  "api_key_env": "ANTHROPIC_API_KEY",
  "worker_cmd": "auto",
  "verify_command": null,
  "default_agent_count": null,
  "worker_timeout_seconds": 120,
  "max_concurrent_workers": 20
}
```

Removed keys: `anthropic_model`, `claude_cmd` (replaced by `provider`, `model`, `api_key_env`, `worker_cmd`).

`worker_cmd`:
- `"auto"` → call `detect_worker_cmd()` at dispatch time; error if nothing found
- Any other string → use as the CLI binary path/name directly

---

## `aide init` Interactive Setup

When `.aide/` does not yet exist, `aide init` prompts interactively:

```
Provider? [anthropic/openai/google/perplexity] (anthropic):
Model? (claude-opus-4-7):
Auth mode? [auto/api_key/subscription] (auto):
API key env var? (ANTHROPIC_API_KEY):
Detected worker CLI: claude ✓
```

`--no-interactive` flag: skip all prompts, write defaults directly.

If subscription mode is chosen for a provider that doesn't support it, print an error and re-prompt.

---

## planner.py Changes

Remove all Anthropic-specific logic. New flow:

```python
from .providers import get_provider, SUPPORTED_PROVIDERS

def plan_task(
    prompt: str,
    provider: str = "anthropic",
    model: str = "claude-opus-4-7",
    auth_mode: str = "auto",
    api_key_env: str = "ANTHROPIC_API_KEY",
    agent_count_override: int | None = None,
) -> Plan:
    api_key = os.environ.get(api_key_env)
    provider_mod = get_provider(provider)
    meta = SUPPORTED_PROVIDERS[provider]
    cli_cmd = meta.get("default_cli_cmd") or "claude"
    raw = provider_mod.generate(
        prompt=_build_planning_prompt(prompt, agent_count_override),
        model=model,
        api_key=api_key,
        auth_mode=auth_mode,
        cli_cmd=cli_cmd,
    )
    return _parse_plan_response(raw, prompt, agent_count_override)
```

Remove: `from anthropic import Anthropic`, `_plan_via_cli`, old `plan_task` signature.

---

## worker.py Changes

Resolve `worker_cmd` before spawning:

```python
from .providers import detect_worker_cmd

async def run_worker(..., worker_cmd: str = "auto") -> None:
    cmd = worker_cmd if worker_cmd != "auto" else detect_worker_cmd()
    if cmd is None:
        # send ERROR message: no worker CLI found
        ...
    proc = await asyncio.create_subprocess_exec(cmd, "--print", ...)
```

---

## cli.py Changes

`run` command reads `provider`, `model`, `auth_mode`, `api_key_env`, `worker_cmd` from config and passes to `plan_task` and `run_manager`.

`init` command gains interactive setup before writing config.

---

## Error Messages

| Situation | Message |
|-----------|---------|
| Unsupported subscription | `"{provider} does not support subscription mode — set auth_mode: api_key"` |
| API key env var not set | `"{api_key_env} is not set. Export it or use auth_mode: subscription."` |
| No worker CLI found | `"No worker CLI found. Install claude, codex, or gemini and ensure it is on PATH."` |
| Unknown provider | `"Unknown provider '{name}'. Supported: anthropic, openai, google, perplexity."` |

---

## Dependencies

```toml
[project]
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.0",
    "httpx>=0.27",        # perplexity + general HTTP
]

[project.optional-dependencies]
openai = ["openai>=1.0"]
google = ["google-generativeai>=0.8"]
all = ["openai>=1.0", "google-generativeai>=0.8"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-mock>=3.12"]
```

`anthropic` stays a core dep (default provider). `openai` and `google-generativeai` are optional extras. `httpx` added to core (small, already likely transitive via anthropic).

---

## Testing

Each provider module tested with mocked SDK/subprocess:
- `test_providers_anthropic.py` — api_key path (mock `Anthropic().messages.create`), subscription path (mock `asyncio.create_subprocess_exec`)
- `test_providers_openai.py` — api_key path (mock `openai.OpenAI`), subscription raises ValueError
- `test_providers_google.py` — api_key path (mock `genai.GenerativeModel`), subscription path
- `test_providers_perplexity.py` — api_key path (mock `httpx.post`), subscription raises ValueError
- `test_providers_init.py` — `get_provider` returns correct module, `detect_worker_cmd` with mocked `shutil.which`
- Existing `test_planner.py` — update mocks to target `aide.providers.anthropic.generate`
- Existing `test_worker.py` — update to pass `worker_cmd="claude"` explicitly (no auto-detect in tests)
- Existing `test_cli.py` — update `init` test for new interactive/non-interactive flow

---

## Success Criteria

- `aide run "task"` works with `provider: anthropic`, `auth_mode: auto`, no API key set (uses `claude` CLI)
- `aide run "task"` works with `provider: openai`, `auth_mode: api_key`, `OPENAI_API_KEY` set
- `aide run "task"` with `provider: openai`, `auth_mode: subscription` → clear error
- `aide init --no-interactive` writes correct default config
- All tests pass with mocked providers
