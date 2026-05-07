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
