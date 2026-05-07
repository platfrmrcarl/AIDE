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
