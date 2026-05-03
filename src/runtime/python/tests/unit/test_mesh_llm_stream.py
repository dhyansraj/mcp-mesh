"""Unit tests for ``MeshLlmAgent.stream()``.

Covers P5 of issue #645:
- Final-iteration streaming yields chunks in order, returns when done.
- Peek-then-stream falls back to the tool-call branch correctly when
  ``tool_calls`` deltas appear in the first chunks.
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
# Peek-then-stream tool-call fallback
# ---------------------------------------------------------------------------


class TestStreamPeekToolCallFallback:
    @pytest.mark.asyncio
    async def test_tool_call_in_first_chunk_falls_back_to_tool_branch(self):
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
    async def test_no_tool_call_drains_buffered_then_live(self):
        # First two chunks land within the peek window; remaining arrive after.
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


# ---------------------------------------------------------------------------
# Regression: peek timeout must not cancel in-flight __anext__()
# ---------------------------------------------------------------------------


class _SlowChunkStream:
    """Async iterator that yields each chunk after a real ``sleep`` delay AND
    fakes litellm's ``CustomStreamWrapper`` failure mode: if a previous
    ``__anext__()`` was cancelled mid-flight (peek timeout firing on a
    chunk-in-flight), the stream is permanently broken and all subsequent
    ``__anext__()`` calls raise ``StopAsyncIteration`` — silently dropping
    every remaining chunk. That's the exact corruption observed empirically
    with real Claude streams.
    """

    def __init__(self, chunks: list[MagicMock], delay_seconds: float):
        self._chunks = list(chunks)
        self._delay = delay_seconds
        self._broken = False
        self.aclosed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        import asyncio as _asyncio

        if self._broken or not self._chunks:
            raise StopAsyncIteration
        try:
            await _asyncio.sleep(self._delay)
        except _asyncio.CancelledError:
            self._broken = True
            raise
        return self._chunks.pop(0)

    async def aclose(self):
        self.aclosed = True


class TestStreamPeekTimeoutDoesNotCancelInFlightChunk:
    @pytest.mark.asyncio
    async def test_yields_all_chunks_when_chunks_arrive_after_peek_timeout(
        self, monkeypatch
    ):
        """Regression: peek must not cancel the in-flight ``__anext__()`` task
        on timeout — chunks arriving after the peek deadline must still be
        yielded.

        Bug: ``asyncio.wait_for`` cancels the underlying coroutine on timeout;
        for litellm's ``CustomStreamWrapper`` that discards the chunk being
        read AND corrupts the iterator state so the post-peek ``async for``
        yields nothing. With a 100ms peek window and 50ms inter-chunk gaps,
        only the first 1–2 chunks arrive before the deadline; without the
        fix the rest are silently dropped.
        """
        monkeypatch.setenv("MESH_LLM_STREAM_PEEK_MS", "100")

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
    async def test_mesh_delegated_raises(self):
        agent = MeshLlmAgent(
            config=LLMConfig(
                provider={"capability": "llm"},
                model="claude-3-5-haiku",
                api_key=None,
                max_iterations=5,
                system_prompt=None,
            ),
            filtered_tools=[],
            output_type=str,
        )

        with pytest.raises(NotImplementedError, match="direct-mode only"):
            async for _ in agent.stream("hi"):
                pass

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
