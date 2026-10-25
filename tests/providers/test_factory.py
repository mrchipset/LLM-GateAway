from __future__ import annotations

import httpx
import respx

from llm_gateway.config import Environment, Settings
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.factory import build_providers
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.schemas.chat import ChatCompletionRequest, ChatMessage
from support import FrozenClock

MASTER_KEY = "test-master-key-0123456789abcdef"

OPENAI_BASE_URL = "https://openai.test/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _settings(**overrides: object) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": MASTER_KEY,
            **overrides,
        }
    )


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="public-model",
        messages=[ChatMessage(role="user", content="hello")],
    )


def _completion_body() -> dict[str, object]:
    return {
        "id": "chatcmpl-upstream",
        "object": "chat.completion",
        "created": 100,
        "model": "upstream-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_deepseek_is_not_registered_without_an_api_key() -> None:
    registry = build_providers(_settings(), clock=FrozenClock())

    assert registry.is_configured(ProviderName.DEEPSEEK) is False


def test_deepseek_is_registered_with_configured_name() -> None:
    registry = build_providers(
        _settings(deepseek_api_key="sk-deepseek-test"),
        clock=FrozenClock(),
    )

    provider = registry.get(ProviderName.DEEPSEEK)

    assert provider.name is ProviderName.DEEPSEEK


async def test_openai_and_deepseek_keep_their_own_base_urls() -> None:
    settings = _settings(
        openai_api_key="sk-openai-test",
        openai_base_url=OPENAI_BASE_URL,
        deepseek_api_key="sk-deepseek-test",
        deepseek_base_url=DEEPSEEK_BASE_URL,
    )
    registry = build_providers(settings, clock=FrozenClock())

    try:
        with respx.mock(assert_all_called=True) as router:
            openai_route = router.post(f"{OPENAI_BASE_URL}/chat/completions").mock(
                return_value=httpx.Response(200, json=_completion_body())
            )
            deepseek_route = router.post(f"{DEEPSEEK_BASE_URL}/chat/completions").mock(
                return_value=httpx.Response(200, json=_completion_body())
            )

            await registry.get(ProviderName.OPENAI).complete(
                upstream_model="gpt-upstream", request=_request()
            )
            await registry.get(ProviderName.DEEPSEEK).complete(
                upstream_model="deepseek-flash", request=_request()
            )

            assert len(openai_route.calls) == 1
            assert len(deepseek_route.calls) == 1
    finally:
        await registry.aclose()


def test_fake_provider_registration_is_unaffected() -> None:
    registry = build_providers(
        _settings(fake_provider_enabled=True),
        clock=FrozenClock(),
    )

    assert isinstance(registry.get(ProviderName.FAKE), FakeProvider)
    assert registry.is_configured(ProviderName.OPENAI) is False
    assert registry.is_configured(ProviderName.DEEPSEEK) is False
