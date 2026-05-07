import pytest
from unittest.mock import MagicMock, patch
from aide.providers.google import generate

MOCK_RESPONSE_TEXT = '{"complexity_score": 20, "agent_count": 3, "tasks": []}'


def test_generate_api_key_calls_sdk(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = MOCK_RESPONSE_TEXT
    mock_model.generate_content.return_value = mock_response

    mock_genai = MagicMock()
    mocker.patch("aide.providers.google.genai", mock_genai)
    mock_genai.GenerativeModel.return_value = mock_model

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
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text=MOCK_RESPONSE_TEXT)

    mock_genai = MagicMock()
    mocker.patch("aide.providers.google.genai", mock_genai)
    mock_genai.GenerativeModel.return_value = mock_model

    generate(
        prompt="task",
        model="gemini-2.0-flash",
        api_key="gm-key-123",
        auth_mode="api_key",
        cli_cmd="gemini",
        system_prompt="",
    )
    mock_genai.configure.assert_called_once_with(api_key="gm-key-123")


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
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text=MOCK_RESPONSE_TEXT)

    mock_genai = MagicMock()
    mocker.patch("aide.providers.google.genai", mock_genai)
    mock_genai.GenerativeModel.return_value = mock_model

    generate(
        prompt="task",
        model="gemini-2.0-flash",
        api_key="gm-key",
        auth_mode="auto",
        cli_cmd="gemini",
        system_prompt="",
    )
    mock_genai.configure.assert_called_once()


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
