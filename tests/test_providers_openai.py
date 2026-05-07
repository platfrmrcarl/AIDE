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
