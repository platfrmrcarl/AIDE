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
    resolve_auth_mode(auth_mode, api_key, False, "openai")
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
