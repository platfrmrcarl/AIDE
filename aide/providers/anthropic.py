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
