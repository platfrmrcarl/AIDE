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
