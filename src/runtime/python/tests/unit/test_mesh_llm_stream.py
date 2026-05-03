"""Unit tests for ``MeshLlmAgent.stream()``.

Covers P5 of issue #645 and the v2 follow-up (always-stream, mid-stream
tool_call detection — Option B):
- Final-iteration streaming yields chunks in order, returns when done.
- Tool-call deltas in the first chunk route through the tool-call branch
  with no text yielded.
- Text preamble that precedes a tool_call IS yielded live, then the
  tool_call is detected mid-stream, the tool runs, and the next iteration's
  text streams normally (regression for #645 v2).
- Chunks arriving with realistic inter-chunk delays still all stream.
- Token usage is captured AFTER full stream consumption and published
  via ``set_llm_metadata`` for ExecutionTracer.
- Direct-mode constraint: mesh-delegated providers raise
  ``NotImplementedError``.
- Output-type constraint: only ``str`` output is streamable.
- Cancellation propagates ``aclose()`` to the litellm stream wrapper.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
from pydantic import BaseModel


def make_config(
    provider: str = "claude",
    model: str = "claude-3-5-haiku-20241022",
    api_key: str = "test-key",
    max_iterations: int = 5,
) -> LLMConfig:
    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
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
# Stream yields chunks
# ---------------------------------------------------------------------------


class TestStreamYieldsChunks:
    @pytest.mark.asyncio
    async def test_yields_chunks_in_order_and_publishes_usage(self):
        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )

        chunks = [
            _chunk(content="Hello", model="claude-3-5-haiku"),
            _chunk(content=", "),
            _chunk(content="world!"),
            _chunk(usage={"prompt_tokens": 12, "completion_tokens": 8}),
        ]

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.return_value = _FakeStream(chunks)

            with patch(
                "_mcp_mesh.tracing.context.set_llm_metadata"
            ) as mock_set_meta:
                collected = []
                async for piece in agent.stream("hi"):
                    collected.append(piece)

                assert collected == ["Hello", ", ", "world!"]
                # Final set_llm_metadata call carries the post-stream usage
                final_call = mock_set_meta.call_args_list[-1]
                assert final_call.kwargs["input_tokens"] == 12
                assert final_call.kwargs["output_tokens"] == 8
                assert final_call.kwargs["model"] == "claude-3-5-haiku"

    @pytest.mark.asyncio
    async def test_passes_stream_options_include_usage(self):
        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.return_value = _FakeStream(
                [_chunk(content="x")]
            )
            async for _ in agent.stream("hi"):
                pass

            call_kwargs = mock_acomp.call_args.kwargs
            assert call_kwargs["stream"] is True
            assert call_kwargs["stream_options"] == {"include_usage": True}


# ---------------------------------------------------------------------------
# Mid-stream tool-call detection (Option B)
# ---------------------------------------------------------------------------


class TestStreamMidStreamToolCall:
    @pytest.mark.asyncio
    async def test_tool_call_in_first_chunk_routes_through_tool_branch(self):
        # Tool call delta arrives in the first chunk, then arguments accrue,
        # then a final text-only iteration completes the stream.
        tool_call_first = _tool_call_delta(
            index=0, id="call_1", type="function", name="weather", arguments="{"
        )
        tool_call_second = _tool_call_delta(index=0, arguments='"city":"SF"}')

        first_iter_chunks = [
            _chunk(tool_calls=[tool_call_first]),
            _chunk(tool_calls=[tool_call_second]),
            _chunk(usage={"prompt_tokens": 5, "completion_tokens": 4}),
        ]
        second_iter_chunks = [
            _chunk(content="Sunny "),
            _chunk(content="and 70F."),
            _chunk(usage={"prompt_tokens": 7, "completion_tokens": 6}),
        ]

        # Mock tool execution
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.side_effect = [
                _FakeStream(first_iter_chunks),
                _FakeStream(second_iter_chunks),
            ]

            with patch.object(
                agent, "_execute_tool_calls", new=AsyncMock(return_value=[])
            ) as mock_exec:
                collected = []
                async for piece in agent.stream("weather in SF?"):
                    collected.append(piece)

                # Final response streamed; tool-call iteration didn't yield text
                assert collected == ["Sunny ", "and 70F."]
                # Tool branch invoked
                assert mock_exec.call_count == 1
                tool_calls_arg = mock_exec.call_args.args[0]
                assert tool_calls_arg[0].function.name == "weather"
                assert tool_calls_arg[0].function.arguments == '{"city":"SF"}'
                # Two iterations against acompletion
                assert mock_acomp.call_count == 2

    @pytest.mark.asyncio
    async def test_text_only_stream_yields_chunks_live(self):
        # No tool_calls — every text chunk should yield in order as it arrives.
        chunks = [
            _chunk(content="A"),
            _chunk(content="B"),
            _chunk(content="C"),
            _chunk(usage={"prompt_tokens": 3, "completion_tokens": 3}),
        ]
        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )
        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.return_value = _FakeStream(chunks)
            collected = []
            async for piece in agent.stream("hi"):
                collected.append(piece)
            assert collected == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_text_preamble_before_tool_call_is_yielded_then_tool_runs(self):
        """Regression for #645 v2: Claude often emits text BEFORE tool_call.

        The previous peek-then-stream design (Option A) saw text first within
        the peek window, decided "no tool calls, this is the final response",
        entered the text-yield branch, ignored the tool_call delta when it
        arrived after the peek window, and returned after the preamble — the
        tool was NEVER executed.

        Option B yields the preamble live as it arrives, detects the
        tool_call mid-stream, drains the rest for full tool_call fragments
        plus the usage chunk, executes the tool, and continues the outer
        loop. The next iteration's text streams normally.
        """
        # Iter 1: text preamble → tool_call delta(s) → usage
        tool_call_first = _tool_call_delta(
            index=0,
            id="call_weather_1",
            type="function",
            name="get_weather",
            arguments='{"city":',
        )
        tool_call_second = _tool_call_delta(
            index=0, arguments='"Charlotte"}'
        )
        first_iter_chunks = [
            _chunk(content="Let me "),
            _chunk(content="check "),
            _chunk(content="the weather..."),
            _chunk(tool_calls=[tool_call_first]),
            _chunk(tool_calls=[tool_call_second]),
            _chunk(usage={"prompt_tokens": 10, "completion_tokens": 8}),
        ]
        # Iter 2: pure text final answer
        second_iter_chunks = [
            _chunk(content="It is "),
            _chunk(content="72°F "),
            _chunk(content="and sunny."),
            _chunk(usage={"prompt_tokens": 14, "completion_tokens": 6}),
        ]

        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.side_effect = [
                _FakeStream(first_iter_chunks),
                _FakeStream(second_iter_chunks),
            ]

            with patch.object(
                agent, "_execute_tool_calls", new=AsyncMock(return_value=[])
            ) as mock_exec:
                collected = []
                async for piece in agent.stream("what's the weather in Charlotte?"):
                    collected.append(piece)

        # Preamble + final answer, in order, all yielded live.
        assert collected == [
            "Let me ",
            "check ",
            "the weather...",
            "It is ",
            "72°F ",
            "and sunny.",
        ]
        # Tool branch executed exactly once with the merged tool call.
        assert mock_exec.call_count == 1
        tool_calls_arg = mock_exec.call_args.args[0]
        assert tool_calls_arg[0].function.name == "get_weather"
        assert tool_calls_arg[0].function.arguments == '{"city":"Charlotte"}'
        # Two acompletion iterations: tool turn + final-answer turn.
        assert mock_acomp.call_count == 2


# ---------------------------------------------------------------------------
# Realistic inter-chunk delays still stream every chunk
# ---------------------------------------------------------------------------


class _SlowChunkStream:
    """Async iterator that yields each chunk after a real ``sleep`` delay.

    Mirrors the timing profile of a real Claude stream where chunks arrive
    tens of milliseconds apart. With Option B (always-stream) there is no
    peek window, so this just verifies live yielding under realistic delays.
    """

    def __init__(self, chunks: list[MagicMock], delay_seconds: float):
        self._chunks = list(chunks)
        self._delay = delay_seconds
        self.aclosed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        import asyncio as _asyncio

        if not self._chunks:
            raise StopAsyncIteration
        await _asyncio.sleep(self._delay)
        return self._chunks.pop(0)

    async def aclose(self):
        self.aclosed = True


class TestStreamYieldsChunksWithRealisticDelays:
    @pytest.mark.asyncio
    async def test_stream_yields_chunks_with_realistic_delays(self):
        """Chunks arriving ~50ms apart must all stream live.

        Originally a regression test for peek-timeout cancelling the
        in-flight ``__anext__()`` task. Option B removes the peek window
        entirely, so the cancel-on-timeout failure mode no longer exists,
        but the realistic-delay scenario itself remains valuable: it
        catches any future regression where buffering re-creeps in.
        """
        chunk_texts = ["chunk1", "chunk2", "chunk3", "chunk4", "chunk5"]
        chunks = [_chunk(content=t) for t in chunk_texts] + [
            _chunk(usage={"prompt_tokens": 3, "completion_tokens": 5})
        ]

        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.return_value = _SlowChunkStream(chunks, delay_seconds=0.05)
            collected = []
            async for piece in agent.stream("hi"):
                collected.append(piece)

        assert collected == chunk_texts


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
            api_key=None,
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

        captured_call_kwargs: dict = {}

        class _FakeProxy:
            endpoint = "http://provider"
            function_name = "claude_provider"

            async def __call__(self, **kwargs):
                captured_call_kwargs.update(kwargs)
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
        assert "request" in captured_call_kwargs
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


# ---------------------------------------------------------------------------
# Helpers used by stream()
# ---------------------------------------------------------------------------


class TestStreamCancellation:
    @pytest.mark.asyncio
    async def test_cancel_during_stream_calls_aclose(self):
        import asyncio

        class _SlowStream:
            def __init__(self):
                self.aclosed = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(1)
                return _chunk(content="x")

            async def aclose(self):
                self.aclosed = True

        slow = _SlowStream()
        agent = MeshLlmAgent(
            config=make_config(),
            filtered_tools=[],
            output_type=str,
        )

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent.acompletion", new=AsyncMock()
        ) as mock_acomp:
            mock_acomp.return_value = slow

            async def consume():
                async for _ in agent.stream("hi"):
                    pass

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert slow.aclosed is True


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
