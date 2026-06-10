import pytest

from app.services.ai.provider import (
    AICompletion,
    FakeAIProvider,
    LiteLLMProvider,
    get_ai_provider,
)


@pytest.mark.asyncio
async def test_fake_provider_returns_fixed_completion_with_cost():
    p = FakeAIProvider(text="yo", input_tokens=3, output_tokens=4, cost_usd=0.002)
    out = await p.complete(
        provider="anthropic",
        model="claude-haiku-4-5",
        api_key="k",
        system="s",
        prompt="p",
        max_tokens=50,
    )
    assert isinstance(out, AICompletion)
    assert out.text == "yo"
    assert out.input_tokens == 3
    assert out.output_tokens == 4
    assert out.cost_usd == 0.002


def test_get_ai_provider_returns_litellm():
    assert isinstance(get_ai_provider(), LiteLLMProvider)


@pytest.mark.asyncio
async def test_litellm_provider_maps_response(monkeypatch):
    """LiteLLMProvider joins 'provider/model', passes the key, maps usage -> AICompletion.

    Mock litellm to avoid network calls — verify mapping + safety when completion_cost fails.
    """
    import sys
    import types

    captured = {}

    class _Msg:
        content = "  hi there  "

    class _Choice:
        message = _Msg()

    class _Usage:
        prompt_tokens = 11
        completion_tokens = 22

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    async def _acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    def _completion_cost(resp):
        return 0.0123

    fake_litellm = types.SimpleNamespace(acompletion=_acompletion, completion_cost=_completion_cost)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    out = await LiteLLMProvider().complete(
        provider="openai",
        model="gpt-4o-mini",
        api_key="sk-x",
        system="sys",
        prompt="usr",
        max_tokens=100,
    )
    assert captured["model"] == "openai/gpt-4o-mini"
    assert captured["api_key"] == "sk-x"
    assert captured["max_tokens"] == 100
    assert out.text == "hi there"  # stripped
    assert out.input_tokens == 11
    assert out.output_tokens == 22
    assert out.cost_usd == 0.0123


@pytest.mark.asyncio
async def test_litellm_reasoning_empty_raises_single_shot_but_degrades_in_tool_loop(monkeypatch):
    # Reasoning model runs out of tokens -> empty content + has reasoning_content. Single-shot: raise a clear error.
    # Tool loop (allow_empty=True): does NOT raise, returns text="" so the runner degrades gracefully.
    import sys
    import types

    class _Msg:
        content = ""
        reasoning_content = "thinking really hard but no answer yet..."
        tool_calls = None

    class _Choice:
        message = _Msg()

    class _Usage:
        prompt_tokens = 5
        completion_tokens = 9

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    async def _acompletion(**kwargs):
        return _Resp()

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        types.SimpleNamespace(acompletion=_acompletion, completion_cost=lambda r: 0.0),
    )
    with pytest.raises(ValueError, match="reasoning"):  # single-shot -> actionable error
        await LiteLLMProvider().complete(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="k",
            system="s",
            prompt="p",
            max_tokens=100,
        )
    out = await LiteLLMProvider().complete(  # tool loop -> degrades gracefully
        provider="deepseek",
        model="deepseek-v4-pro",
        api_key="k",
        system="s",
        prompt="p",
        max_tokens=100,
        allow_empty=True,
    )
    assert out.text == ""


@pytest.mark.asyncio
async def test_litellm_provider_cost_failure_falls_back_to_zero(monkeypatch):
    import sys
    import types

    class _Msg:
        content = "x"

    class _Choice:
        message = _Msg()

    class _Usage:
        prompt_tokens = 1
        completion_tokens = 1

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    async def _acompletion(**kwargs):
        return _Resp()

    def _completion_cost(resp):
        raise RuntimeError("unknown model pricing")

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        types.SimpleNamespace(acompletion=_acompletion, completion_cost=_completion_cost),
    )

    out = await LiteLLMProvider().complete(
        provider="groq",
        model="weird",
        api_key="k",
        system="s",
        prompt="p",
        max_tokens=10,
    )
    assert out.cost_usd == 0.0  # cost error -> 0, no crash


@pytest.mark.asyncio
async def test_litellm_provider_includes_history(monkeypatch):
    import sys
    import types

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Usage:
        prompt_tokens = 1
        completion_tokens = 1

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    async def _acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        types.SimpleNamespace(acompletion=_acompletion, completion_cost=lambda r: 0.0),
    )
    await LiteLLMProvider().complete(
        provider="openai",
        model="gpt-4o-mini",
        api_key="k",
        system="sys",
        prompt="now",
        max_tokens=50,
        history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
    )
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert captured["messages"][-1]["content"] == "now"


@pytest.mark.asyncio
async def test_fake_provider_scripted_tool_calls():
    p = FakeAIProvider(
        turns=[
            {"tool_calls": [{"id": "c1", "name": "web_search", "arguments": '{"query":"x"}'}]},
            {"text": "final result"},
        ]
    )
    first = await p.complete(
        provider="p",
        model="m",
        api_key="k",
        system="",
        prompt="",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function"}],
    )
    assert first.tool_calls and first.tool_calls[0]["name"] == "web_search"
    assert first.raw_message["role"] == "assistant"
    second = await p.complete(
        provider="p",
        model="m",
        api_key="k",
        system="",
        prompt="",
        max_tokens=10,
        messages=[],
        tools=None,
    )
    assert second.text == "final result"
    assert second.tool_calls is None


@pytest.mark.asyncio
async def test_litellm_uses_messages_and_tools(monkeypatch):
    import sys
    import types

    captured = {}

    class _Fn:
        name = "web_search"
        arguments = '{"query":"x"}'

    class _TC:
        id = "c1"
        function = _Fn()

    class _Msg:
        content = None
        tool_calls = [_TC()]

    class _Choice:
        message = _Msg()

    class _Usage:
        prompt_tokens = 2
        completion_tokens = 3

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    async def _acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        types.SimpleNamespace(acompletion=_acompletion, completion_cost=lambda r: 0.0),
    )
    out = await LiteLLMProvider().complete(
        provider="openai",
        model="gpt-4o-mini",
        api_key="k",
        system="",
        prompt="",
        max_tokens=50,
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
    )
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["tools"][0]["function"]["name"] == "web_search"
    assert out.tool_calls[0] == {"id": "c1", "name": "web_search", "arguments": '{"query":"x"}'}
    assert out.raw_message["tool_calls"][0]["function"]["name"] == "web_search"
