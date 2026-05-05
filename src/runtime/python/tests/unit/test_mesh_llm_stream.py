"""Unit tests for ``MeshLlmAgent.stream()`` (mesh-delegated only in v2).

Covers:
- Mesh-delegated streaming routes to the provider's auto-generated
  ``<name>_stream`` tool, with soft-fallback to the buffered tool when
  the streaming variant isn't exposed (older providers).
- Output-type constraint: only ``str`` output is streamable.
- Streaming chunk merge / extraction helpers (used both consumer-side
  and provider-side via ``mesh.helpers``).
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
from pydantic import BaseModel


def make_config(
    model: str = "claude-3-5-haiku-20241022",
    max_iterations: int = 5,
) -> LLMConfig:
    """Mesh-delegated test config (provider is always a dict in v2)."""
    return LLMConfig(
        provider={"capability": "llm", "tags": ["claude"]},
        model=model,
        max_iterations=max_iterations,
        system_prompt=None,
    )


# ---------------------------------------------------------------------------
# Streaming chunk fakes mirroring litellm.acompletion(stream=True) shape
# ---------------------------------------------------------------------------


def _delta(content: str | None = None, tool_calls: list | None = None) -> MagicMock:
    d = MagicMock()
    d.content = content
    d.tool_calls = tool_calls
    return d


def _choice(delta: MagicMock) -> MagicMock:
    c = MagicMock()
    c.delta = delta
    return c


def _chunk(
    content: str | None = None,
    tool_calls: list | None = None,
    usage: dict | None = None,
    model: str | None = None,
) -> MagicMock:
    ch = MagicMock()
    ch.choices = [_choice(_delta(content=content, tool_calls=tool_calls))]
    ch.usage = (
        MagicMock(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        if usage
        else None
    )
    ch.model = model
    return ch


def _tool_call_delta(
    index: int,
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
    type: str | None = None,
) -> MagicMock:
    tc = MagicMock()
    tc.index = index
    tc.id = id
    tc.type = type
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments
    tc.function = fn
    return tc


class _FakeStream:
    """Minimal async-iterable that yields chunks then stops, with aclose()."""

    def __init__(self, chunks: list[MagicMock]):
        self._chunks = list(chunks)
        self.aclosed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self):
        self.aclosed = True


# ---------------------------------------------------------------------------
# Constraints: mesh-delegated and typed output reject
# ---------------------------------------------------------------------------


class TestStreamConstraints:
    @pytest.mark.asyncio
    async def test_typed_output_raises(self):
        class Resp(BaseModel):
            answer: str

        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=Resp,
        )
        with pytest.raises(NotImplementedError, match="str output_type"):
            async for _ in agent.stream("hi"):
                pass


# ---------------------------------------------------------------------------
# Mesh-delegated streaming (Phase 4 — issue #849)
# ---------------------------------------------------------------------------


def _make_mesh_agent(
    parallel_tool_calls: bool = False,
    output_type: type = str,
) -> MeshLlmAgent:
    """Build a mesh-delegated MeshLlmAgent with no tools and a given proxy."""
    return MeshLlmAgent(
        config=LLMConfig(
            provider={"capability": "llm"},
            model="claude-3-5-haiku",
            max_iterations=5,
            system_prompt=None,
        ),
        filtered_tools=[],
        output_type=output_type,
        parallel_tool_calls=parallel_tool_calls,
    )


class _FakeAsyncIter:
    """Minimal async iterator over a list of values."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class TestMeshDelegatedStreaming:
    """Phase 4: ``MeshLlmAgent.stream()`` for mesh-delegated providers."""

    @pytest.mark.asyncio
    async def test_routes_to_stream_variant(self):
        """Per Phase 5C tag-based discrimination, the resolver returns the
        streaming-variant tool directly (via ai.mcpmesh.stream tag match), so
        ``provider_proxy.function_name`` IS the streaming tool name. No suffix
        mangling — call the proxy with that name as-is."""
        agent = _make_mesh_agent()

        proxy = MagicMock()
        proxy.endpoint = "http://provider"
        proxy.function_name = "claude_provider_stream"

        captured: dict = {}

        def fake_stream(*, name, request):
            captured["name"] = name
            captured["request"] = request
            return _FakeAsyncIter(["Hello, ", "world", "!"])

        proxy.stream = MagicMock(side_effect=fake_stream)
        agent._mesh_provider_proxy = proxy

        collected: list[str] = []
        async for piece in agent.stream("hi"):
            collected.append(piece)

        assert collected == ["Hello, ", "world", "!"]
        assert captured["name"] == "claude_provider_stream"
        # Request shape mirrors _call_mesh_provider: same five keys.
        assert set(captured["request"].keys()) >= {
            "messages",
            "tools",
            "model_params",
            "context",
            "request_id",
            "caller_agent",
        }

    @pytest.mark.asyncio
    async def test_falls_back_when_stream_variant_missing(self, caplog):
        """ToolError("Unknown tool: ...") triggers buffered single-chunk fallback.

        We hand-build the proxy as a small class instead of MagicMock so the
        ``__call__`` protocol is unambiguously async and there's only one
        place to patch behavior.
        """
        from fastmcp.exceptions import ToolError

        # Resolver gives us the streaming variant (function_name ends in
        # "_stream"); the fallback must explicitly invoke the buffered
        # sibling (without the suffix), not re-call the streaming tool.
        captured_buffered_name: list[str] = []
        captured_buffered_args: dict = {}

        class _FakeProxy:
            endpoint = "http://provider"
            function_name = "claude_provider_stream"

            async def __call__(self, **kwargs):
                # Should NOT be reached — fallback must use call_tool_with_tracing
                # with the explicit buffered name, not __call__ which would
                # re-invoke the streaming tool name.
                raise AssertionError(
                    "fallback must call call_tool_with_tracing with the "
                    "buffered name, not provider_proxy(request=...)"
                )

            async def call_tool_with_tracing(self, name, arguments):
                captured_buffered_name.append(name)
                captured_buffered_args.update(arguments)
                return {
                    "role": "assistant",
                    "content": "Buffered final response.",
                }

            def stream(self, *, name, request):
                async def _raise():
                    raise ToolError(f"Unknown tool: {name}")
                    yield  # pragma: no cover

                return _raise()

        agent = _make_mesh_agent()
        agent._mesh_provider_proxy = _FakeProxy()

        with caplog.at_level("WARNING"):
            collected: list[str] = []
            async for piece in agent.stream("hi"):
                collected.append(piece)

        assert collected == ["Buffered final response."]
        # Fallback invoked the buffered sibling, NOT the streaming tool name.
        assert captured_buffered_name == ["claude_provider"]
        assert "request" in captured_buffered_args
        assert any(
            "advertised the streaming variant but tool" in rec.message
            and "is not exposed" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_non_unknown_tool_error_propagates(self):
        """A non-"unknown tool" ToolError must NOT trigger the fallback."""
        from fastmcp.exceptions import ToolError

        agent = _make_mesh_agent()

        proxy = MagicMock()
        proxy.endpoint = "http://provider"
        proxy.function_name = "claude_provider"

        async def raise_other(*args, **kwargs):
            raise ToolError("Anthropic API rate limited")
            yield  # pragma: no cover

        proxy.stream = MagicMock(return_value=raise_other())
        agent._mesh_provider_proxy = proxy

        with pytest.raises(ToolError, match="rate limited"):
            async for _ in agent.stream("hi"):
                pass

    @pytest.mark.asyncio
    async def test_passes_parallel_tool_calls_in_model_params(self):
        """parallel_tool_calls=True must end up in ``request.model_params``."""
        agent = _make_mesh_agent(parallel_tool_calls=True)

        proxy = MagicMock()
        proxy.endpoint = "http://provider"
        proxy.function_name = "claude_provider"

        captured: dict = {}

        def fake_stream(*, name, request):
            captured["request"] = request
            return _FakeAsyncIter(["x"])

        proxy.stream = MagicMock(side_effect=fake_stream)
        agent._mesh_provider_proxy = proxy

        async for _ in agent.stream("hi"):
            pass

        assert captured["request"]["model_params"]["parallel_tool_calls"] is True

    @pytest.mark.asyncio
    async def test_request_shape_unchanged_from_call_mesh_provider(self):
        """Streaming and buffered paths build the same request keys."""
        agent = _make_mesh_agent()

        proxy = MagicMock()
        proxy.endpoint = "http://provider"
        proxy.function_name = "claude_provider"

        captured: dict = {}

        def fake_stream(*, name, request):
            captured["request"] = request
            return _FakeAsyncIter([])

        proxy.stream = MagicMock(side_effect=fake_stream)
        agent._mesh_provider_proxy = proxy

        async for _ in agent.stream("hi"):
            pass

        # Same five keys + request_id + caller_agent that _call_mesh_provider
        # writes (see mesh_llm_agent.py:580-587).
        assert set(captured["request"].keys()) == {
            "messages",
            "tools",
            "model_params",
            "context",
            "request_id",
            "caller_agent",
        }
class TestStreamHelpers:
    def test_merge_streamed_tool_calls_concatenates_arguments_per_index(self):
        chunks = [
            _chunk(
                tool_calls=[
                    _tool_call_delta(index=0, id="A", type="function", name="f")
                ]
            ),
            _chunk(
                tool_calls=[_tool_call_delta(index=0, arguments='{"a":')]
            ),
            _chunk(tool_calls=[_tool_call_delta(index=0, arguments="1}")]),
            _chunk(
                tool_calls=[
                    _tool_call_delta(index=1, id="B", type="function", name="g")
                ]
            ),
            _chunk(tool_calls=[_tool_call_delta(index=1, arguments="{}")]),
        ]
        merged = MeshLlmAgent._merge_streamed_tool_calls(chunks)
        assert len(merged) == 2
        assert merged[0]["id"] == "A"
        assert merged[0]["function"]["name"] == "f"
        assert merged[0]["function"]["arguments"] == '{"a":1}'
        assert merged[1]["id"] == "B"
        assert merged[1]["function"]["arguments"] == "{}"

    def test_extract_text_from_chunk_handles_missing_delta(self):
        empty = MagicMock()
        empty.choices = []
        assert MeshLlmAgent._extract_text_from_chunk(empty) == ""

    def test_extract_usage_returns_last_non_empty(self):
        chunks = [
            _chunk(content="x"),
            _chunk(usage={"prompt_tokens": 10, "completion_tokens": 20}),
        ]
        usage = MeshLlmAgent._extract_usage_from_chunks(chunks)
        assert usage == {"prompt_tokens": 10, "completion_tokens": 20}

    def test_extract_usage_returns_none_when_absent(self):
        chunks = [_chunk(content="x")]
        assert MeshLlmAgent._extract_usage_from_chunks(chunks) is None
