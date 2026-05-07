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
