import pytest

from app.services.ai.provider import AICompletion, AnthropicAIProvider, FakeAIProvider


@pytest.mark.asyncio
async def test_fake_provider_returns_fixed_completion():
    p = FakeAIProvider(text="yo", input_tokens=3, output_tokens=4)
    assert p.available is True
    out = await p.complete(system="s", prompt="p", max_tokens=50)
    assert isinstance(out, AICompletion)
    assert out.text == "yo"
    assert out.input_tokens == 3
    assert out.output_tokens == 4


def test_anthropic_available_reflects_key():
    assert AnthropicAIProvider(api_key="", model="m").available is False
    assert AnthropicAIProvider(api_key="sk-x", model="m").available is True
