"""Issue #1356: the consumer's ``max_iterations`` must reach the
provider-managed agentic loop.

Before the fix the provider loop was invoked with a hardcoded ``10`` and the
consumer never put the value on the wire, so a ``@mesh.llm(max_iterations=...)``
setting was inert for every mesh-delegated consumer.

Contract (matches the TypeScript reference in ``llm-agent.ts`` /
``llm-provider.ts``):

  * Consumer forwards ``model_params.max_iterations`` ONLY when explicitly
    configured (decorator arg or ``MESH_LLM_MAX_ITERATIONS``).
  * Provider resolves: forwarded value → its own ``MESH_LLM_MAX_ITERATIONS``
    → 10. A *present* but invalid forwarded value falls back to 10 and does
    NOT consult env.
  * The key is stripped provider-side so it never reaches the vendor API.
"""

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
from mesh.helpers import (
    DEFAULT_MAX_ITERATIONS,
    _MAX_ITERATIONS_UNSET,
    _resolve_max_iterations,
    _sanitize_max_iterations,
)


# ---------------------------------------------------------------------------
# Sanitization / resolution (parity with TS sanitizeMaxIterations)
# ---------------------------------------------------------------------------


class TestSanitizeMaxIterations:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (3, 3),
            ("7", 7),
            (2.9, 2),  # floored
            ("2.9", 2),
            (1, 1),
            (0, None),
            (-1, None),
            (0.5, None),  # floors to 0 BEFORE the >0 check — not a zero cap
            ("0", None),
            ("-4", None),
            ("abc", None),
            ("", None),
            (None, None),
            (float("nan"), None),
            (float("inf"), None),
            ([], None),
            ({}, None),
        ],
    )
    def test_sanitize(self, value, expected):
        assert _sanitize_max_iterations(value) == expected


class TestResolveMaxIterations:
    def test_valid_param_wins(self, monkeypatch):
        monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "4")
        assert _resolve_max_iterations(6) == 6

    def test_invalid_explicit_param_falls_back_to_default_not_env(self, monkeypatch):
        """A *present* param never falls through to env — invalid → 10."""
        monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "4")
        for bad in (0, -3, "abc", None, float("nan")):
            assert _resolve_max_iterations(bad) == DEFAULT_MAX_ITERATIONS

    def test_absent_param_uses_env(self, monkeypatch):
        monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "4")
        assert _resolve_max_iterations() == 4
        assert _resolve_max_iterations(_MAX_ITERATIONS_UNSET) == 4

    def test_absent_param_invalid_env_uses_default(self, monkeypatch):
        monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "not-a-number")
        assert _resolve_max_iterations() == DEFAULT_MAX_ITERATIONS

    def test_absent_param_no_env_uses_default(self, monkeypatch):
        monkeypatch.delenv("MESH_LLM_MAX_ITERATIONS", raising=False)
        assert _resolve_max_iterations() == DEFAULT_MAX_ITERATIONS


# ---------------------------------------------------------------------------
# LLMConfig: None means "not explicitly configured"
# ---------------------------------------------------------------------------


def _config(max_iterations=None) -> LLMConfig:
    return LLMConfig(
        provider={"capability": "llm"},
        model=None,
        max_iterations=max_iterations,
        system_prompt=None,
    )


class TestLLMConfigDefaults:
    def test_unset_is_none_but_effective_is_ten(self):
        cfg = _config()
        assert cfg.max_iterations is None
        assert cfg.effective_max_iterations == 10
        assert cfg.max_iterations_explicit is False

    def test_explicit_value_is_kept(self):
        cfg = _config(3)
        assert cfg.effective_max_iterations == 3
        assert cfg.max_iterations_explicit is True

    def test_explicit_ten_is_still_explicit(self):
        assert _config(10).max_iterations_explicit is True

    def test_zero_still_rejected(self):
        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            _config(0)


# ---------------------------------------------------------------------------
# Consumer: forwards on the wire only when explicitly configured
# ---------------------------------------------------------------------------


def _agent(max_iterations, provider_proxy) -> MeshLlmAgent:
    return MeshLlmAgent(
        config=_config(max_iterations),
        filtered_tools=[],
        output_type=str,
        provider_proxy=provider_proxy,
        vendor="anthropic",
    )


class TestConsumerForwarding:
    @pytest.mark.asyncio
    async def test_buffered_forwards_when_explicit(self):
        captured: dict = {}

        async def provider(request):
            captured["request"] = request
            return {"role": "assistant", "content": "done"}

        assert await _agent(4, provider)("hi") == "done"
        assert captured["request"]["model_params"]["max_iterations"] == 4

    @pytest.mark.asyncio
    async def test_buffered_omits_when_unset(self):
        captured: dict = {}

        async def provider(request):
            captured["request"] = request
            return {"role": "assistant", "content": "done"}

        assert await _agent(None, provider)("hi") == "done"
        model_params = captured["request"]["model_params"] or {}
        assert "max_iterations" not in model_params

    @pytest.mark.asyncio
    async def test_stream_forwards_when_explicit(self):
        agent = _agent(6, None)
        captured: dict = {}

        class _FakeAsyncIter:
            def __init__(self, items):
                self._items = list(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._items:
                    raise StopAsyncIteration
                return self._items.pop(0)

        proxy = MagicMock()
        proxy.endpoint = "http://provider"
        proxy.function_name = "claude_provider_stream"
        proxy.stream = MagicMock(
            side_effect=lambda *, name, request: (
                captured.update(request=request),
                _FakeAsyncIter(["ok"]),
            )[1]
        )
        agent._mesh_provider_proxy = proxy

        collected = [piece async for piece in agent.stream("hi")]
        assert collected == ["ok"]
        assert captured["request"]["model_params"]["max_iterations"] == 6

    @pytest.mark.asyncio
    async def test_stream_omits_when_unset(self):
        agent = _agent(None, None)
        captured: dict = {}

        class _FakeAsyncIter:
            def __init__(self, items):
                self._items = list(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._items:
                    raise StopAsyncIteration
                return self._items.pop(0)

        proxy = MagicMock()
        proxy.endpoint = "http://provider"
        proxy.function_name = "claude_provider_stream"
        proxy.stream = MagicMock(
            side_effect=lambda *, name, request: (
                captured.update(request=request),
                _FakeAsyncIter(["ok"]),
            )[1]
        )
        agent._mesh_provider_proxy = proxy

        collected = [piece async for piece in agent.stream("hi")]
        assert collected == ["ok"]
        assert "max_iterations" not in (captured["request"]["model_params"] or {})


# ---------------------------------------------------------------------------
# Decorator: unset stays unset; decorator arg / env mark it explicit
# ---------------------------------------------------------------------------


class TestDecoratorResolution:
    def _config_for(self, **llm_kwargs) -> dict:
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        snapshot = dict(DecoratorRegistry._mesh_llm_agents)
        DecoratorRegistry._mesh_llm_agents.clear()
        try:

            @mesh.llm(provider={"capability": "llm"}, **llm_kwargs)
            def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
                return ""

            agent_data = next(iter(DecoratorRegistry.get_mesh_llm_agents().values()))
            return agent_data.config
        finally:
            DecoratorRegistry._mesh_llm_agents.clear()
            DecoratorRegistry._mesh_llm_agents.update(snapshot)

    def test_unset_resolves_to_none(self, monkeypatch):
        monkeypatch.delenv("MESH_LLM_MAX_ITERATIONS", raising=False)
        assert self._config_for()["max_iterations"] is None

    def test_decorator_arg_is_explicit(self, monkeypatch):
        monkeypatch.delenv("MESH_LLM_MAX_ITERATIONS", raising=False)
        assert self._config_for(max_iterations=3)["max_iterations"] == 3

    def test_env_marks_explicit_without_decorator_arg(self, monkeypatch):
        """A consumer-side env var counts as "explicitly configured": it drives
        the consumer's own loop AND goes on the wire."""
        monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "7")
        assert self._config_for()["max_iterations"] == 7

    def test_env_wins_over_decorator_arg(self, monkeypatch):
        monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "7")
        assert self._config_for(max_iterations=3)["max_iterations"] == 7


# ---------------------------------------------------------------------------
# Provider: honours the forwarded value, strips the key
# ---------------------------------------------------------------------------


def _make_provider_module(module_name: str):
    """Register a @mesh.llm_provider in a throwaway module with a FastMCP app."""
    import sys

    from fastmcp import FastMCP

    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    mod = types.ModuleType(module_name)
    mod.app = FastMCP(module_name)
    sys.modules[module_name] = mod
    snapshot = dict(DecoratorRegistry._mesh_tools)
    DecoratorRegistry._mesh_tools.clear()
    return mod, snapshot


def _drop_provider_module(module_name: str, snapshot: dict):
    import sys

    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    sys.modules.pop(module_name, None)
    DecoratorRegistry._mesh_tools.clear()
    DecoratorRegistry._mesh_tools.update(snapshot)


def _decorate_provider(mod, module_name: str, func_name: str):
    import mesh

    def placeholder():
        pass

    placeholder.__name__ = func_name
    placeholder.__qualname__ = func_name
    placeholder.__module__ = module_name
    decorated = mesh.llm_provider(
        model="anthropic/claude-3-5-haiku-20241022",
        capability="llm",
        tags=["claude"],
    )(placeholder)
    setattr(mod, func_name, decorated)
    return decorated


def _tool_with_endpoint() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "noop_tool",
            "description": "noop",
            "parameters": {"type": "object", "properties": {}},
            "_mesh_endpoint": "http://tool-agent:9090",
        },
    }


class TestProviderResolution:
    """Drives the auto-generated ``process_chat`` and inspects what the
    provider-managed loop receives."""

    def _buffered_handler(self, mod):
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        wrapper = DecoratorRegistry.get_mesh_tools()["claude_provider"].function
        return getattr(wrapper, "_mesh_original_func", wrapper)

    async def _run(self, monkeypatch, model_params: dict | None, env: str | None):
        from mesh.types import MeshLlmRequest

        module_name = "_test_max_iterations_provider"
        mod, snapshot = _make_provider_module(module_name)
        try:
            _decorate_provider(mod, module_name, "claude_provider")
            handler = self._buffered_handler(mod)

            if env is None:
                monkeypatch.delenv("MESH_LLM_MAX_ITERATIONS", raising=False)
            else:
                monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", env)

            captured: dict = {}

            async def fake_loop(**kwargs):
                captured.update(kwargs)
                return {"role": "assistant", "content": "done"}

            request = MeshLlmRequest(
                messages=[{"role": "user", "content": "hi"}],
                tools=[_tool_with_endpoint()],
                model_params=model_params,
            )
            with patch("mesh.helpers._provider_agentic_loop", new=fake_loop):
                await handler(request)
            return captured
        finally:
            _drop_provider_module(module_name, snapshot)

    @pytest.mark.asyncio
    async def test_forwarded_value_is_honoured(self, monkeypatch):
        captured = await self._run(
            monkeypatch, {"max_iterations": 3}, env="8"
        )
        assert captured["max_iterations"] == 3
        # ...and never reaches the vendor call params.
        assert "max_iterations" not in captured["model_params"]

    @pytest.mark.asyncio
    async def test_invalid_forwarded_value_falls_back_to_default(self, monkeypatch):
        captured = await self._run(monkeypatch, {"max_iterations": 0}, env="8")
        assert captured["max_iterations"] == DEFAULT_MAX_ITERATIONS
        assert "max_iterations" not in captured["model_params"]

    @pytest.mark.asyncio
    async def test_absent_uses_provider_env(self, monkeypatch):
        captured = await self._run(monkeypatch, None, env="8")
        assert captured["max_iterations"] == 8

    @pytest.mark.asyncio
    async def test_absent_without_env_uses_default(self, monkeypatch):
        captured = await self._run(monkeypatch, None, env=None)
        assert captured["max_iterations"] == DEFAULT_MAX_ITERATIONS

    @pytest.mark.asyncio
    async def test_key_never_reaches_litellm_on_legacy_no_tools_path(
        self, monkeypatch
    ):
        """No tool endpoints → single litellm call. The consumer-only key must
        not appear in completion args (vendor APIs reject unknown params)."""
        monkeypatch.setenv("MCP_MESH_NATIVE_LLM", "0")
        from mesh.types import MeshLlmRequest

        module_name = "_test_max_iterations_provider_legacy"
        mod, snapshot = _make_provider_module(module_name)
        try:
            _decorate_provider(mod, module_name, "claude_provider")
            handler = self._buffered_handler(mod)

            message = MagicMock()
            message.content = "hello"
            message.role = "assistant"
            message.tool_calls = None
            choice = MagicMock()
            choice.message = message
            response = MagicMock()
            response.choices = [choice]
            response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
            response.model = "claude-3-5-haiku"

            request = MeshLlmRequest(
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                model_params={"max_iterations": 5, "temperature": 0.1},
            )

            with patch(
                "asyncio.to_thread", new=AsyncMock(return_value=response)
            ) as mock_thread:
                await handler(request)

            completion_kwargs = mock_thread.call_args.kwargs
            assert "max_iterations" not in completion_kwargs
            assert completion_kwargs["temperature"] == 0.1
        finally:
            _drop_provider_module(module_name, snapshot)
