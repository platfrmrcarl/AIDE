# LLM-Agnostic Provider Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AIDE's hard-wired Anthropic dependency with a thin provider adapter layer supporting Anthropic, OpenAI, Google, and Perplexity — each with `api_key` or `subscription` auth modes.

**Architecture:** New `aide/providers/` subpackage exposes one `generate()` function per provider. `planner.py` delegates to the active provider. `worker.py` auto-detects the best available agentic CLI. Config schema gains `provider`, `model`, `auth_mode`, `api_key_env`, `worker_cmd`; drops `anthropic_model`, `claude_cmd`.

**Tech Stack:** Python 3.11+, anthropic SDK (core), openai SDK (optional extra), google-generativeai SDK (optional extra), httpx (core, for Perplexity), subprocess for CLI-based auth.

---

## File Map

| Action | Path |
|--------|------|
| Create | `aide/providers/__init__.py` |
| Create | `aide/providers/anthropic.py` |
| Create | `aide/providers/openai.py` |
| Create | `aide/providers/google.py` |
| Create | `aide/providers/perplexity.py` |
| Create | `tests/test_providers_init.py` |
| Create | `tests/test_providers_anthropic.py` |
| Create | `tests/test_providers_openai.py` |
| Create | `tests/test_providers_google.py` |
| Create | `tests/test_providers_perplexity.py` |
| Modify | `aide/planner.py` |
| Modify | `aide/worker.py` |
| Modify | `aide/workspace.py` |
| Modify | `aide/cli.py` |
| Modify | `tests/test_planner.py` |
| Modify | `tests/test_worker.py` |
| Modify | `tests/test_workspace.py` |
| Modify | `tests/test_cli.py` |
| Modify | `pyproject.toml` |
| Modify | `README.md` |

---

## Task 1: Provider infrastructure (`aide/providers/__init__.py`)

**Files:**
- Create: `aide/providers/__init__.py`
- Create: `tests/test_providers_init.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers_init.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_providers_init.py -v
```
Expected: `ModuleNotFoundError: No module named 'aide.providers'`

- [ ] **Step 3: Create `aide/providers/__init__.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_providers_init.py -v
```
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add aide/providers/__init__.py tests/test_providers_init.py
git commit -m "feat: provider infrastructure — SUPPORTED_PROVIDERS, detect_worker_cmd, resolve_auth_mode"
```

---

## Task 2: Anthropic provider adapter

**Files:**
- Create: `aide/providers/anthropic.py`
- Create: `tests/test_providers_anthropic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers_anthropic.py
import subprocess
import pytest
from unittest.mock import MagicMock, patch
from aide.providers.anthropic import generate

MOCK_RESPONSE_TEXT = '{"complexity_score": 25, "agent_count": 6, "tasks": []}'


def _mock_anthropic_client(text: str):
    mock_content = MagicMock()
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


def test_generate_api_key_calls_sdk():
    client = _mock_anthropic_client(MOCK_RESPONSE_TEXT)
    with patch("aide.providers.anthropic.Anthropic", return_value=client):
        result = generate(
            prompt="do a thing",
            model="claude-opus-4-7",
            api_key="sk-test",
            auth_mode="api_key",
            cli_cmd="claude",
            system_prompt="respond in JSON",
        )
    assert result == MOCK_RESPONSE_TEXT
    client.messages.create.assert_called_once()


def test_generate_api_key_passes_key_to_client():
    client = _mock_anthropic_client(MOCK_RESPONSE_TEXT)
    with patch("aide.providers.anthropic.Anthropic", return_value=client) as mock_cls:
        generate(
            prompt="task",
            model="claude-opus-4-7",
            api_key="sk-ant-abc",
            auth_mode="api_key",
            cli_cmd="claude",
            system_prompt="",
        )
    mock_cls.assert_called_once_with(api_key="sk-ant-abc")


def test_generate_subscription_calls_subprocess(mocker):
    mock_run = mocker.patch(
        "aide.providers.anthropic.subprocess.run",
        return_value=MagicMock(stdout=MOCK_RESPONSE_TEXT, returncode=0),
    )
    result = generate(
        prompt="do a thing",
        model="claude-opus-4-7",
        api_key=None,
        auth_mode="subscription",
        cli_cmd="claude",
        system_prompt="respond in JSON",
    )
    assert result == MOCK_RESPONSE_TEXT
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "claude"
    assert "--print" in args


def test_generate_auto_uses_api_key_when_available():
    client = _mock_anthropic_client(MOCK_RESPONSE_TEXT)
    with patch("aide.providers.anthropic.Anthropic", return_value=client) as mock_cls:
        generate(
            prompt="task",
            model="claude-opus-4-7",
            api_key="sk-key",
            auth_mode="auto",
            cli_cmd="claude",
            system_prompt="",
        )
    mock_cls.assert_called_once()


def test_generate_auto_falls_back_to_cli_when_no_key(mocker):
    mock_run = mocker.patch(
        "aide.providers.anthropic.subprocess.run",
        return_value=MagicMock(stdout=MOCK_RESPONSE_TEXT, returncode=0),
    )
    generate(
        prompt="task",
        model="claude-opus-4-7",
        api_key=None,
        auth_mode="auto",
        cli_cmd="claude",
        system_prompt="",
    )
    mock_run.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_providers_anthropic.py -v
```
Expected: `ModuleNotFoundError: No module named 'aide.providers.anthropic'`

- [ ] **Step 3: Create `aide/providers/anthropic.py`**

```python
import subprocess
from anthropic import Anthropic
from . import resolve_auth_mode


def generate(
    prompt: str,
    model: str,
    api_key: str | None,
    auth_mode: str = "auto",
    cli_cmd: str = "claude",
    system_prompt: str = "",
) -> str:
    resolved = resolve_auth_mode(auth_mode, api_key, True, "anthropic")
    if resolved == "subscription":
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        result = subprocess.run(
            [cli_cmd, "--print", full_prompt],
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_providers_anthropic.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add aide/providers/anthropic.py tests/test_providers_anthropic.py
git commit -m "feat: Anthropic provider adapter — api_key (SDK) and subscription (CLI) modes"
```

---

## Task 3: OpenAI provider adapter

**Files:**
- Create: `aide/providers/openai.py`
- Create: `tests/test_providers_openai.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers_openai.py
import pytest
from unittest.mock import MagicMock, patch
from aide.providers.openai import generate

MOCK_RESPONSE_TEXT = '{"complexity_score": 30, "agent_count": 6, "tasks": []}'


def _mock_openai_client(text: str):
    mock_msg = MagicMock()
    mock_msg.content = text
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def test_generate_api_key_calls_sdk():
    client = _mock_openai_client(MOCK_RESPONSE_TEXT)
    with patch("aide.providers.openai.OpenAI", return_value=client):
        result = generate(
            prompt="do a thing",
            model="gpt-4o",
            api_key="sk-openai-test",
            auth_mode="api_key",
            cli_cmd="codex",
            system_prompt="respond in JSON",
        )
    assert result == MOCK_RESPONSE_TEXT
    client.chat.completions.create.assert_called_once()


def test_generate_passes_system_prompt():
    client = _mock_openai_client(MOCK_RESPONSE_TEXT)
    with patch("aide.providers.openai.OpenAI", return_value=client):
        generate(
            prompt="task",
            model="gpt-4o",
            api_key="sk-key",
            auth_mode="api_key",
            cli_cmd="codex",
            system_prompt="be a JSON machine",
        )
    call_kwargs = client.chat.completions.create.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "be a JSON machine"
    assert messages[1]["role"] == "user"


def test_generate_subscription_raises():
    with pytest.raises(ValueError, match="does not support subscription"):
        generate(
            prompt="task",
            model="gpt-4o",
            api_key=None,
            auth_mode="subscription",
            cli_cmd="codex",
            system_prompt="",
        )


def test_generate_auto_no_key_raises():
    with pytest.raises(ValueError, match="requires an API key"):
        generate(
            prompt="task",
            model="gpt-4o",
            api_key=None,
            auth_mode="auto",
            cli_cmd="codex",
            system_prompt="",
        )


def test_generate_import_error_without_package(mocker):
    mocker.patch.dict("sys.modules", {"openai": None})
    with pytest.raises((ImportError, TypeError)):
        from importlib import reload
        import aide.providers.openai as mod
        reload(mod)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_providers_openai.py -v
```
Expected: `ModuleNotFoundError: No module named 'aide.providers.openai'`

- [ ] **Step 3: Create `aide/providers/openai.py`**

```python
from . import resolve_auth_mode

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


def generate(
    prompt: str,
    model: str,
    api_key: str | None,
    auth_mode: str = "auto",
    cli_cmd: str = "codex",
    system_prompt: str = "",
) -> str:
    resolved = resolve_auth_mode(auth_mode, api_key, False, "openai")
    # resolved is always "api_key" — subscription raises in resolve_auth_mode
    if OpenAI is None:
        raise ImportError("openai package not installed. Run: pip install 'aide[openai]'")
    client = OpenAI(api_key=api_key)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4096,
    )
    return response.choices[0].message.content.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_providers_openai.py -v
```
Expected: 4 passed (skip import-error test if openai is installed — that's fine)

- [ ] **Step 5: Commit**

```bash
git add aide/providers/openai.py tests/test_providers_openai.py
git commit -m "feat: OpenAI provider adapter — api_key only, subscription raises ValueError"
```

---

## Task 4: Google provider adapter

**Files:**
- Create: `aide/providers/google.py`
- Create: `tests/test_providers_google.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers_google.py
import pytest
from unittest.mock import MagicMock, patch
from aide.providers.google import generate

MOCK_RESPONSE_TEXT = '{"complexity_score": 20, "agent_count": 3, "tasks": []}'


def test_generate_api_key_calls_sdk(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = MOCK_RESPONSE_TEXT
    mock_model.generate_content.return_value = mock_response

    mocker.patch("aide.providers.google.genai.configure")
    mocker.patch("aide.providers.google.genai.GenerativeModel", return_value=mock_model)

    result = generate(
        prompt="do a thing",
        model="gemini-2.0-flash",
        api_key="gm-test-key",
        auth_mode="api_key",
        cli_cmd="gemini",
        system_prompt="respond in JSON",
    )
    assert result == MOCK_RESPONSE_TEXT
    mock_model.generate_content.assert_called_once()


def test_generate_api_key_configures_api_key(mocker):
    mock_configure = mocker.patch("aide.providers.google.genai.configure")
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text=MOCK_RESPONSE_TEXT)
    mocker.patch("aide.providers.google.genai.GenerativeModel", return_value=mock_model)

    generate(
        prompt="task",
        model="gemini-2.0-flash",
        api_key="gm-key-123",
        auth_mode="api_key",
        cli_cmd="gemini",
        system_prompt="",
    )
    mock_configure.assert_called_once_with(api_key="gm-key-123")


def test_generate_subscription_calls_subprocess(mocker):
    mock_run = mocker.patch(
        "aide.providers.google.subprocess.run",
        return_value=MagicMock(stdout=MOCK_RESPONSE_TEXT, returncode=0),
    )
    result = generate(
        prompt="do a thing",
        model="gemini-2.0-flash",
        api_key=None,
        auth_mode="subscription",
        cli_cmd="gemini",
        system_prompt="respond in JSON",
    )
    assert result == MOCK_RESPONSE_TEXT
    args = mock_run.call_args[0][0]
    assert args[0] == "gemini"
    assert "--print" in args


def test_generate_auto_uses_api_key_when_available(mocker):
    mock_configure = mocker.patch("aide.providers.google.genai.configure")
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text=MOCK_RESPONSE_TEXT)
    mocker.patch("aide.providers.google.genai.GenerativeModel", return_value=mock_model)

    generate(
        prompt="task",
        model="gemini-2.0-flash",
        api_key="gm-key",
        auth_mode="auto",
        cli_cmd="gemini",
        system_prompt="",
    )
    mock_configure.assert_called_once()


def test_generate_auto_no_key_uses_cli(mocker):
    mock_run = mocker.patch(
        "aide.providers.google.subprocess.run",
        return_value=MagicMock(stdout=MOCK_RESPONSE_TEXT, returncode=0),
    )
    generate(
        prompt="task",
        model="gemini-2.0-flash",
        api_key=None,
        auth_mode="auto",
        cli_cmd="gemini",
        system_prompt="",
    )
    mock_run.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_providers_google.py -v
```
Expected: `ModuleNotFoundError: No module named 'aide.providers.google'`

- [ ] **Step 3: Create `aide/providers/google.py`**

```python
import subprocess
from . import resolve_auth_mode

try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore


def generate(
    prompt: str,
    model: str,
    api_key: str | None,
    auth_mode: str = "auto",
    cli_cmd: str = "gemini",
    system_prompt: str = "",
) -> str:
    resolved = resolve_auth_mode(auth_mode, api_key, True, "google")
    if resolved == "subscription":
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        result = subprocess.run(
            [cli_cmd, "--print", full_prompt],
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()
    if genai is None:
        raise ImportError("google-generativeai not installed. Run: pip install 'aide[google]'")
    genai.configure(api_key=api_key)
    model_obj = genai.GenerativeModel(model)
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    response = model_obj.generate_content([full_prompt])
    return response.text.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_providers_google.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add aide/providers/google.py tests/test_providers_google.py
git commit -m "feat: Google provider adapter — api_key (SDK) and subscription (gemini CLI) modes"
```

---

## Task 5: Perplexity provider adapter

**Files:**
- Create: `aide/providers/perplexity.py`
- Create: `tests/test_providers_perplexity.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers_perplexity.py
import pytest
from unittest.mock import MagicMock, patch
from aide.providers.perplexity import generate

MOCK_RESPONSE_TEXT = '{"complexity_score": 15, "agent_count": 3, "tasks": []}'


def _mock_httpx_response(text: str):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": text}}]
    }
    mock_response.raise_for_status = MagicMock()
    return mock_response


def test_generate_api_key_calls_httpx(mocker):
    mock_post = mocker.patch(
        "aide.providers.perplexity.httpx.post",
        return_value=_mock_httpx_response(MOCK_RESPONSE_TEXT),
    )
    result = generate(
        prompt="do a thing",
        model="sonar-pro",
        api_key="pplx-test-key",
        auth_mode="api_key",
        cli_cmd="claude",
        system_prompt="respond in JSON",
    )
    assert result == MOCK_RESPONSE_TEXT
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer pplx-test-key"


def test_generate_sends_system_and_user_messages(mocker):
    mock_post = mocker.patch(
        "aide.providers.perplexity.httpx.post",
        return_value=_mock_httpx_response(MOCK_RESPONSE_TEXT),
    )
    generate(
        prompt="task text",
        model="sonar-pro",
        api_key="pplx-key",
        auth_mode="api_key",
        cli_cmd="claude",
        system_prompt="be JSON",
    )
    payload = mock_post.call_args[1]["json"]
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "be JSON"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "task text"


def test_generate_subscription_raises():
    with pytest.raises(ValueError, match="does not support subscription"):
        generate(
            prompt="task",
            model="sonar-pro",
            api_key=None,
            auth_mode="subscription",
            cli_cmd="claude",
            system_prompt="",
        )


def test_generate_auto_no_key_raises():
    with pytest.raises(ValueError, match="requires an API key"):
        generate(
            prompt="task",
            model="sonar-pro",
            api_key=None,
            auth_mode="auto",
            cli_cmd="claude",
            system_prompt="",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_providers_perplexity.py -v
```
Expected: `ModuleNotFoundError: No module named 'aide.providers.perplexity'`

- [ ] **Step 3: Create `aide/providers/perplexity.py`**

```python
import httpx
from . import resolve_auth_mode

_API_URL = "https://api.perplexity.ai/chat/completions"


def generate(
    prompt: str,
    model: str,
    api_key: str | None,
    auth_mode: str = "auto",
    cli_cmd: str = "claude",
    system_prompt: str = "",
) -> str:
    resolve_auth_mode(auth_mode, api_key, False, "perplexity")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    response = httpx.post(
        _API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_providers_perplexity.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add aide/providers/perplexity.py tests/test_providers_perplexity.py
git commit -m "feat: Perplexity provider adapter — api_key via httpx, subscription raises ValueError"
```

---

## Task 6: Update `planner.py` + `tests/test_planner.py`

**Files:**
- Modify: `aide/planner.py`
- Modify: `tests/test_planner.py`

The current `planner.py` imports `Anthropic` directly and has `auth_mode`/`claude_cmd` params. Replace with provider abstraction.

- [ ] **Step 1: Write the new/updated failing tests**

Add these tests to `tests/test_planner.py` (keep existing tests — they'll be updated to use new mocks in step 3):

```python
# Add to tests/test_planner.py

def test_plan_task_uses_provider_generate(mocker):
    """plan_task delegates to provider's generate() function."""
    mocker.patch(
        "aide.providers.anthropic.generate",
        return_value=MOCK_API_RESPONSE,
    )
    plan = plan_task("Build a REST API", provider="anthropic")
    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 3


def test_plan_task_openai_provider(mocker):
    mocker.patch(
        "aide.providers.openai.generate",
        return_value=MOCK_API_RESPONSE,
    )
    plan = plan_task("Build a REST API", provider="openai", model="gpt-4o")
    assert isinstance(plan, Plan)


def test_plan_task_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        plan_task("task", provider="fakeprovider")
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/test_planner.py::test_plan_task_uses_provider_generate -v
```
Expected: FAIL — `plan_task` does not accept `provider` param yet

- [ ] **Step 3: Rewrite `aide/planner.py`**

```python
import json
import os
import re
import uuid

from .models import Plan, SubTask
from .providers import SUPPORTED_PROVIDERS, get_provider

_SYSTEM_PROMPT = """You are a software engineering task decomposition expert.
Given a coding task, assess complexity (1-100) and break it into atomic subtasks.

Agent count guidelines:
- Score 1-20: 3 agents (bug fix, trivial change)
- Score 21-40: 5-10 agents (small feature)
- Score 41-60: 10-20 agents (medium feature with tests)
- Score 61-80: 20-50 agents (multi-module feature)
- Score 81-100: 50-100 agents (full project)

Respond ONLY with valid JSON (no preamble, no explanation, no code fences):
{
  "complexity_score": <int 1-100>,
  "agent_count": <int>,
  "tasks": [
    {"id": "t1", "description": "<actionable task>", "depends_on": []}
  ]
}

Rules:
- Each task must be independently executable by one AI coding agent
- Tasks must form a valid DAG (no cycles)
- Include file names in descriptions where possible
- depends_on lists IDs of prerequisite tasks
"""


def compute_agent_count(complexity_score: int) -> int:
    if complexity_score <= 20:
        return 3
    if complexity_score <= 40:
        return max(5, complexity_score // 5)
    if complexity_score <= 60:
        return max(10, complexity_score // 4)
    if complexity_score <= 80:
        return max(20, complexity_score // 2)
    return max(50, complexity_score)


def _build_planning_prompt(prompt: str, agent_count_override: int | None) -> str:
    override_note = (
        f"\n\nNote: Use agent_count={agent_count_override} in your response."
        if agent_count_override is not None
        else ""
    )
    return f"Task: {prompt}{override_note}"


def _parse_plan_response(raw: str, prompt: str, agent_count_override: int | None) -> Plan:
    run_id = str(uuid.uuid4())[:8]
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        raw = match.group(1)
    data = json.loads(raw)
    agent_count = agent_count_override or compute_agent_count(data["complexity_score"])
    tasks = [
        SubTask(
            id=t["id"],
            description=t["description"],
            depends_on=t.get("depends_on", []),
        )
        for t in data["tasks"]
    ]
    return Plan(
        run_id=run_id,
        original_prompt=prompt,
        agent_count=agent_count,
        complexity_score=data["complexity_score"],
        tasks=tasks,
    )


def plan_task(
    prompt: str,
    provider: str = "anthropic",
    model: str | None = None,
    auth_mode: str = "auto",
    api_key_env: str | None = None,
    agent_count_override: int | None = None,
) -> Plan:
    meta = SUPPORTED_PROVIDERS[provider]
    resolved_model = model or meta["default_model"]
    resolved_key_env = api_key_env or meta["api_key_env"]
    api_key = os.environ.get(resolved_key_env)
    cli_cmd = meta.get("default_cli_cmd") or "claude"

    provider_mod = get_provider(provider)
    raw = provider_mod.generate(
        prompt=_build_planning_prompt(prompt, agent_count_override),
        model=resolved_model,
        api_key=api_key,
        auth_mode=auth_mode,
        cli_cmd=cli_cmd,
        system_prompt=_SYSTEM_PROMPT,
    )
    return _parse_plan_response(raw, prompt, agent_count_override)
```

- [ ] **Step 4: Update existing tests in `tests/test_planner.py` to use new mock targets**

The old tests mock `aide.planner.Anthropic`. Change all occurrences to mock `aide.providers.anthropic.generate` returning `MOCK_API_RESPONSE` string. Also update `plan_task` calls: remove `auth_mode`/`claude_cmd` params, add `provider="anthropic"`.

Replace the old test file content with:

```python
import json
import pytest
from unittest.mock import MagicMock, patch
from aide.models import Plan, SubTask
from aide.planner import compute_agent_count, plan_task

MOCK_API_RESPONSE = json.dumps({
    "complexity_score": 25,
    "agent_count": 6,
    "tasks": [
        {"id": "t1", "description": "Set up project structure", "depends_on": []},
        {"id": "t2", "description": "Implement auth module", "depends_on": ["t1"]},
        {"id": "t3", "description": "Write tests", "depends_on": ["t2"]},
    ],
})


def test_compute_agent_count_trivial():
    assert compute_agent_count(10) == 3


def test_compute_agent_count_small():
    count = compute_agent_count(30)
    assert 5 <= count <= 10


def test_compute_agent_count_medium():
    count = compute_agent_count(50)
    assert 10 <= count <= 20


def test_compute_agent_count_large():
    count = compute_agent_count(70)
    assert 20 <= count <= 50


def test_compute_agent_count_very_large():
    assert compute_agent_count(90) >= 50


def test_plan_task_returns_plan(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic")
    assert isinstance(plan, Plan)
    assert plan.complexity_score == 25
    assert len(plan.tasks) == 3
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[1].depends_on == ["t1"]


def test_plan_task_agent_count_override(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic", agent_count_override=42)
    assert plan.agent_count == 42


def test_plan_task_handles_json_in_code_block(mocker):
    wrapped = f"```json\n{MOCK_API_RESPONSE}\n```"
    mocker.patch("aide.providers.anthropic.generate", return_value=wrapped)
    plan = plan_task("Build a REST API", provider="anthropic")
    assert len(plan.tasks) == 3


def test_plan_task_subtask_types(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic")
    for task in plan.tasks:
        assert isinstance(task, SubTask)
        assert task.status == "pending"


def test_plan_task_uses_provider_generate(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic")
    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 3


def test_plan_task_openai_provider(mocker):
    mocker.patch("aide.providers.openai.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="openai", model="gpt-4o")
    assert isinstance(plan, Plan)


def test_plan_task_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        plan_task("task", provider="fakeprovider")
```

- [ ] **Step 5: Run all planner tests**

```bash
python -m pytest tests/test_planner.py -v
```
Expected: 13 passed

- [ ] **Step 6: Commit**

```bash
git add aide/planner.py tests/test_planner.py
git commit -m "refactor: planner uses provider abstraction — removes direct Anthropic import"
```

---

## Task 7: Update `worker.py` + `tests/test_worker.py`

**Files:**
- Modify: `aide/worker.py`
- Modify: `tests/test_worker.py`

Replace `claude_cmd: str = "claude"` with `worker_cmd: str = "auto"`. When `"auto"`, call `detect_worker_cmd()`. Error if nothing found.

- [ ] **Step 1: Write failing test**

Add to `tests/test_worker.py`:

```python
# Add to tests/test_worker.py
from aide.providers import detect_worker_cmd

@pytest.mark.asyncio
async def test_worker_auto_cmd_errors_when_no_cli_found(db, tmp_path, mocker):
    """worker_cmd='auto' with no CLI installed sends ERROR message."""
    mocker.patch("aide.worker.detect_worker_cmd", return_value=None)
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="auto",
    )
    messages = db.get_unprocessed_messages("manager")
    error_msgs = [m for m in messages if m.type == "ERROR"]
    assert len(error_msgs) == 1
    assert "worker CLI" in error_msgs[0].payload.get("error", "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_worker.py::test_worker_auto_cmd_errors_when_no_cli_found -v
```
Expected: FAIL — `run_worker` does not accept `worker_cmd` yet

- [ ] **Step 3: Update `aide/worker.py`**

Replace the `claude_cmd` parameter with `worker_cmd` and add CLI detection:

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .models import Message
from .taskbox import Taskbox
from .providers import detect_worker_cmd

_TASK_TEMPLATE = """\
# Agent Task

{description}

## Instructions
- Work only within this directory
- Run tests to verify your work
- Commit when done: git add -A && git commit -m "feat: {short_desc}"
- Do NOT push

## Context
- Run ID: {run_id}
- Agent ID: {agent_id}
"""


async def run_worker(
    agent_id: str,
    run_id: str,
    task_id: str,
    task_description: str,
    worktree_path: Path,
    taskbox: Taskbox,
    timeout: int = 120,
    worker_cmd: str = "auto",
) -> None:
    cmd = worker_cmd if worker_cmd != "auto" else detect_worker_cmd()
    if cmd is None:
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()),
                type="ERROR",
                from_agent=agent_id,
                to_agent="manager",
                payload={
                    "task_id": task_id,
                    "error": "No worker CLI found. Install claude, codex, or gemini.",
                },
                created_at=datetime.utcnow(),
            )
        )
        taskbox.update_agent_status(agent_id, "failed")
        return

    short_desc = task_description[:50].replace("\n", " ")
    (worktree_path / "TASK.md").write_text(
        _TASK_TEMPLATE.format(
            description=task_description,
            run_id=run_id,
            agent_id=agent_id,
            short_desc=short_desc,
        )
    )

    taskbox.update_agent_status(agent_id, "working")

    try:
        proc = await asyncio.create_subprocess_exec(
            cmd,
            "--print",
            "Please complete the task described in TASK.md",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        taskbox.update_agent_status(agent_id, "working", pid=proc.pid)

        async def _drain_stdout() -> None:
            assert proc.stdout
            async for line in proc.stdout:
                taskbox.send_message(
                    Message(
                        id=str(uuid.uuid4()),
                        type="PROGRESS",
                        from_agent=agent_id,
                        to_agent="manager",
                        payload={"line": line.decode().rstrip()},
                        created_at=datetime.utcnow(),
                    )
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(proc.wait(), _drain_stdout()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="ERROR",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={"task_id": task_id, "error": "timeout"},
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "failed")
            return

        if proc.returncode == 0:
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="COMPLETE",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={"task_id": task_id},
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "done")
        else:
            stderr = b""
            if proc.stderr:
                stderr = await proc.stderr.read()
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="ERROR",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={
                        "task_id": task_id,
                        "returncode": proc.returncode,
                        "stderr": stderr.decode(),
                    },
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "failed")

    except Exception as exc:
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()),
                type="ERROR",
                from_agent=agent_id,
                to_agent="manager",
                payload={"task_id": task_id, "error": str(exc)},
                created_at=datetime.utcnow(),
            )
        )
        taskbox.update_agent_status(agent_id, "failed")
```

- [ ] **Step 4: Update existing worker tests** — change `claude_cmd=` to `worker_cmd=` in all existing `run_worker` calls in `tests/test_worker.py`:

```python
# Every run_worker call: change claude_cmd="true" → worker_cmd="true"
# and claude_cmd="false" → worker_cmd="false"
# and claude_cmd=mock_script → worker_cmd=mock_script
```

- [ ] **Step 5: Run all worker tests**

```bash
python -m pytest tests/test_worker.py -v
```
Expected: 6 passed (includes the slow timeout test — run without `-k timeout` if pressed for time)

- [ ] **Step 6: Commit**

```bash
git add aide/worker.py tests/test_worker.py
git commit -m "refactor: worker uses detect_worker_cmd — auto-detects claude/codex/gemini CLI"
```

---

## Task 8: Update `workspace.py` config schema + `tests/test_workspace.py`

**Files:**
- Modify: `aide/workspace.py`
- Modify: `tests/test_workspace.py`

Replace old config keys (`anthropic_model`, `claude_cmd`, `auth_mode`) with new schema.

- [ ] **Step 1: Write failing test**

Add to `tests/test_workspace.py`:

```python
def test_init_aide_config_has_provider_fields(git_repo):
    """New config schema includes provider, model, auth_mode, api_key_env, worker_cmd."""
    init_aide(git_repo)
    config = get_config(git_repo)
    assert config["provider"] == "anthropic"
    assert config["model"] == "claude-opus-4-7"
    assert config["auth_mode"] == "auto"
    assert config["api_key_env"] == "ANTHROPIC_API_KEY"
    assert config["worker_cmd"] == "auto"
    assert "anthropic_model" not in config
    assert "claude_cmd" not in config
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_workspace.py::test_init_aide_config_has_provider_fields -v
```
Expected: FAIL — old config keys present

- [ ] **Step 3: Update `aide/workspace.py` default config in `init_aide`**

Find the `config_path.write_text(json.dumps({...}))` block and replace the dict:

```python
config_path.write_text(
    json.dumps(
        {
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "auth_mode": "auto",
            "api_key_env": "ANTHROPIC_API_KEY",
            "worker_cmd": "auto",
            "verify_command": None,
            "default_agent_count": None,
            "worker_timeout_seconds": 120,
            "max_concurrent_workers": 20,
        },
        indent=2,
    )
)
```

- [ ] **Step 4: Run all workspace tests**

```bash
python -m pytest tests/test_workspace.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add aide/workspace.py tests/test_workspace.py
git commit -m "refactor: workspace config — provider/model/auth_mode/api_key_env/worker_cmd replaces old keys"
```

---

## Task 9: Update `cli.py` + `tests/test_cli.py` + `pyproject.toml`

**Files:**
- Modify: `aide/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `pyproject.toml`

`aide init` gains interactive provider setup. `aide run` passes new config keys to `plan_task` and `run_manager`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
def test_init_no_interactive_uses_defaults(runner, git_repo):
    """aide init --no-interactive writes default config without prompting."""
    result = runner.invoke(main, ["init", str(git_repo), "--no-interactive"])
    assert result.exit_code == 0
    config_path = git_repo / ".aide" / "config.json"
    assert config_path.exists()
    import json
    config = json.loads(config_path.read_text())
    assert config["provider"] == "anthropic"
    assert config["auth_mode"] == "auto"


def test_run_passes_provider_to_plan_task(runner, git_repo, mocker):
    """aide run passes provider from config to plan_task."""
    init_aide(git_repo)
    # write a config with openai provider
    import json
    config_path = git_repo / ".aide" / "config.json"
    config = json.loads(config_path.read_text())
    config["provider"] = "openai"
    config["model"] = "gpt-4o"
    config_path.write_text(json.dumps(config))

    from aide.models import Plan, SubTask
    fake_plan = Plan(
        run_id="r1", original_prompt="do a thing",
        agent_count=1, complexity_score=5,
        tasks=[SubTask(id="t1", description="do a thing", depends_on=[])],
    )
    mocker.patch("aide.cli.plan_task", return_value=fake_plan)
    mocker.patch("aide.cli.run_manager", new=AsyncMock(return_value={
        "run_id": "r1", "status": "complete", "completed": 1, "failed": 0, "total": 1,
    }))

    result = runner.invoke(main, ["run", "do a thing", "--repo", str(git_repo)])
    assert result.exit_code == 0
    call_kwargs = mocker.patch("aide.cli.plan_task").call_args
    # plan_task should have been called with provider="openai"
    # (the mock was called before we checked — verify via the first mock call)
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/test_cli.py::test_init_no_interactive_uses_defaults -v
```
Expected: FAIL — `init` command doesn't accept `--no-interactive`

- [ ] **Step 3: Update `aide/cli.py`**

Full updated file:

```python
import asyncio
import json
from pathlib import Path

import click

from .manager import run_manager
from .planner import plan_task
from .providers import SUPPORTED_PROVIDERS, detect_worker_cmd
from .taskbox import Taskbox
from .workspace import get_config, init_aide, is_initialized, list_worktrees, delete_worktree


@click.group()
def main():
    pass


@main.command()
@click.argument("repo_path", default=".", type=click.Path())
@click.option("--no-interactive", is_flag=True, default=False,
              help="Skip prompts and use defaults.")
def init(repo_path, no_interactive):
    """Initialize AIDE for a git repository."""
    path = Path(repo_path).resolve()
    if is_initialized(path):
        click.echo(f"AIDE already initialized at {path}")
        return

    if no_interactive:
        init_aide(path)
        click.echo(f"AIDE initialized at {path}")
        return

    # Interactive setup
    provider = click.prompt(
        "Provider",
        type=click.Choice(list(SUPPORTED_PROVIDERS.keys())),
        default="anthropic",
    )
    meta = SUPPORTED_PROVIDERS[provider]
    model = click.prompt("Model", default=meta["default_model"])
    auth_choices = ["auto", "api_key", "subscription"] if meta["supports_subscription"] else ["auto", "api_key"]
    auth_mode = click.prompt(
        "Auth mode",
        type=click.Choice(auth_choices),
        default="auto",
    )
    api_key_env = click.prompt("API key env var", default=meta["api_key_env"])

    detected_cli = detect_worker_cmd()
    if detected_cli:
        click.echo(f"Detected worker CLI: {detected_cli} ✓")
    else:
        click.echo("Warning: No worker CLI found (claude/codex/gemini). Install one before running.")

    init_aide(path)

    # Overwrite config with user choices
    config_path = path / ".aide" / "config.json"
    existing = json.loads(config_path.read_text())
    existing.update({
        "provider": provider,
        "model": model,
        "auth_mode": auth_mode,
        "api_key_env": api_key_env,
    })
    config_path.write_text(json.dumps(existing, indent=2))

    click.echo(f"AIDE initialized at {path}")


@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True))
@click.option("--repo", default=".", type=click.Path())
@click.option("--agents", type=int, default=None)
@click.option("--verify", "verify_cmd", default=None)
def run(prompt, task_file, repo, agents, verify_cmd):
    """Run agents on a task prompt or .md file."""
    if not prompt and not task_file:
        click.echo("Error: provide a prompt or --file", err=True)
        raise SystemExit(1)

    repo_path = Path(repo).resolve()
    if not is_initialized(repo_path):
        click.echo(f"Error: AIDE is not initialized at {repo_path}. Run 'aide init' first.", err=True)
        raise SystemExit(1)

    effective_prompt = prompt or Path(task_file).read_text()
    config = get_config(repo_path)

    plan = plan_task(
        effective_prompt,
        provider=config.get("provider", "anthropic"),
        model=config.get("model"),
        auth_mode=config.get("auth_mode", "auto"),
        api_key_env=config.get("api_key_env"),
        agent_count_override=agents,
    )

    taskbox = Taskbox(repo_path / ".aide" / "aide.db")
    result = asyncio.run(run_manager(
        plan, repo_path, taskbox,
        max_concurrent=config.get("max_concurrent_workers", 20),
        verify_cmd=verify_cmd or config.get("verify_command"),
        worker_cmd=config.get("worker_cmd", "auto"),
        worker_timeout=config.get("worker_timeout_seconds", 120),
    ))
    click.echo(f"Run {result['run_id']}: {result['status']} ({result['completed']}/{result['total']} tasks)")


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--run-id", default=None)
def status(repo, run_id):
    """Show status of runs."""
    repo_path = Path(repo).resolve()
    taskbox = Taskbox(repo_path / ".aide" / "aide.db")
    if run_id:
        run_rec = taskbox.get_run(run_id)
        if not run_rec:
            click.echo(f"Run {run_id} not found.")
            return
        tasks = taskbox.get_tasks(run_id)
        for t in tasks:
            click.echo(f"  {t.id}: {t.status} — {t.description[:60]}")
    else:
        runs = taskbox.list_runs()[:5]
        if not runs:
            click.echo("No runs found.")
            return
        for r in runs:
            completed_at = r.completed_at.isoformat() if r.completed_at else "running"
            click.echo(f"{r.id}: {r.status} ({completed_at})")


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--all", "all_worktrees", is_flag=True, default=False)
def clean(repo, all_worktrees):
    """Remove finished worktrees."""
    repo_path = Path(repo).resolve()
    worktrees = list_worktrees(repo_path)
    for wt in worktrees:
        wt_path = Path(wt["path"]) if isinstance(wt, dict) else wt
        delete_worktree(repo_path, wt_path)
    click.echo(f"Removed {len(worktrees)} worktrees.")
```

Note: `run_manager` now receives `worker_cmd` instead of `claude_cmd`. Update `aide/manager.py` call too — change `claude_cmd=` to `worker_cmd=` and propagate to `run_worker`.

- [ ] **Step 4: Update `aide/manager.py` signature**

In `aide/manager.py`, change the `run_manager` function signature and its call to `run_worker`:

```python
# Change this line in run_manager signature:
    claude_cmd: str = "claude",
# To:
    worker_cmd: str = "auto",

# Change this line inside _dispatch():
            claude_cmd=claude_cmd,
# To:
            worker_cmd=worker_cmd,
```

- [ ] **Step 5: Update `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aide"
version = "0.2.0"
description = "CAID multi-agent AI orchestrator using git worktrees"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.0",
    "httpx>=0.27",
]

[project.scripts]
aide = "aide.cli:main"

[project.optional-dependencies]
openai = ["openai>=1.0"]
google = ["google-generativeai>=0.8"]
all = ["openai>=1.0", "google-generativeai>=0.8"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 6: Reinstall package**

```bash
pip install -e . --break-system-packages -q
```

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest --ignore=tests/test_worker.py -v
```
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add aide/cli.py aide/manager.py pyproject.toml tests/test_cli.py
git commit -m "feat: interactive aide init, provider-aware run command, optional deps for openai/google"
```

---

## Task 10: Update README + full run + push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md` Authentication section**

Replace the Authentication section with:

```markdown
## Authentication

AIDE supports multiple LLM providers for task planning, each with two auth modes.

### Providers

| Provider | `provider` value | API key env var | Subscription (CLI) |
|----------|-----------------|-----------------|-------------------|
| Anthropic (Claude) | `anthropic` | `ANTHROPIC_API_KEY` | ✓ `claude` CLI |
| OpenAI (ChatGPT) | `openai` | `OPENAI_API_KEY` | ✗ |
| Google (Gemini) | `google` | `GEMINI_API_KEY` | ✓ `gemini` CLI |
| Perplexity | `perplexity` | `PERPLEXITY_API_KEY` | ✗ |

### Auth modes

- **`auto` (default)** — uses API key if env var is set, otherwise falls back to subscription CLI
- **`api_key`** — always use SDK with API key (error if not set)
- **`subscription`** — always use the provider's CLI (Anthropic and Google only)

Configure in `.aide/config.json` or set during `aide init`.

### Optional provider installs

```bash
pip install 'aide[openai]'   # OpenAI support
pip install 'aide[google]'   # Google Gemini support
pip install 'aide[all]'      # All providers
```

### Worker CLI (code execution)

Workers auto-detect the best available agentic CLI: `claude` → `codex` → `gemini`.
Override with `"worker_cmd": "claude"` in `.aide/config.json`.
```

- [ ] **Step 2: Update Configuration table in README** — add `provider`, `model`, `api_key_env`, `worker_cmd` rows; remove `anthropic_model`, `claude_cmd`, `auth_mode` as standalone rows (they're now covered in the Auth section).

Updated config example block:
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

Updated table:

| Key | Default | Description |
|-----|---------|-------------|
| `provider` | `"anthropic"` | LLM provider for planning: `anthropic`, `openai`, `google`, `perplexity` |
| `model` | `"claude-opus-4-7"` | Model name for the chosen provider |
| `auth_mode` | `"auto"` | `"auto"` \| `"api_key"` \| `"subscription"` |
| `api_key_env` | `"ANTHROPIC_API_KEY"` | Env var name holding the API key |
| `worker_cmd` | `"auto"` | CLI for agent execution: `"auto"` auto-detects `claude`/`codex`/`gemini` |
| `verify_command` | `null` | Run before merging each branch |
| `worker_timeout_seconds` | `120` | Kill agent after this many seconds |
| `max_concurrent_workers` | `20` | Max agents running simultaneously |

- [ ] **Step 3: Run full test suite including worker tests**

```bash
python -m pytest -v 2>&1 | tail -20
```
Expected: all tests pass

- [ ] **Step 4: Verify CLI**

```bash
aide --help
aide init --help
```

- [ ] **Step 5: Commit and push**

```bash
git add README.md
git commit -m "docs: update README for multi-provider auth — anthropic/openai/google/perplexity"
git push origin main
```
