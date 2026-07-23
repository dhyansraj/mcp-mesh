"""Unit tests for ``_provider_agentic_loop_stream`` (mesh.helpers).

Phase 2 of the mesh-delegate streaming work for issue #849.

The streaming counterpart to ``_provider_agentic_loop`` mirrors the buffered
loop one-for-one but yields text chunks live as they arrive from
``litellm.acompletion(stream=True, ...)``. These tests pin down the contract:

  * Text-only iterations yield chunks in order.
  * Tool-call iterations execute tools internally (via the Phase 1 helper)
    and feed results back into the loop.
  * Text preamble before a tool_call IS yielded live; subsequent text
    deltas after the tool_call are dropped (Anthropic doesn't interleave).
  * Parallel tool calls dispatch via the Phase 1 helper's parallel branch.
  * HINT mode buffers the final iteration for schema validation, then
    yields the validated/fallback content as a single chunk.
  * Vendor restrictions on images in tool messages flow through unchanged.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _mcp_mesh.engine.llm_stop_reason import (
    encode_chunk,
    encode_end,
    parse_stream_frame,
)


def _texts(frames: list[str]) -> list[str]:
    """Unwrap the ``content`` of every ``chunk`` frame, skipping the terminal
    ``end`` frame. Also asserts every emitted item IS a well-formed typed
    frame (issue #1355: the provider frames every chunk)."""
    out: list[str] = []
    for f in frames:
        frame = parse_stream_frame(f)
        assert frame is not None, f"expected a typed stream frame, got {f!r}"
        if frame["_mesh_frame"] == "chunk":
            out.append(frame["content"])
    return out


@pytest.fixture(autouse=True)
def _force_litellm_path(monkeypatch):
    """Force the LiteLLM path for every test in this module.

    Issue #834 flipped MCP_MESH_NATIVE_LLM from opt-in to opt-out. These
    tests mock ``litellm.acompletion`` directly to verify the agentic-loop
    contract, so they explicitly disable native dispatch — otherwise the
    loop would route around litellm and the mock would never be hit.
    """
    monkeypatch.setenv("MCP_MESH_NATIVE_LLM", "0")


# ---------------------------------------------------------------------------
# Streaming chunk fakes mirroring litellm.acompletion(stream=True) shape.
# Kept independent from test_mesh_llm_stream.py so each test file is
# self-contained.
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
# No tools: text-only single iteration
# ---------------------------------------------------------------------------


class TestTextOnlySingleIteration:
    @pytest.mark.asyncio
    async def test_yields_chunks_in_order(self):
        from mesh.helpers import _provider_agentic_loop_stream

        chunks = [
            _chunk(content="Hello", model="claude-3-5-haiku"),
            _chunk(content=", "),
            _chunk(content="world!"),
            _chunk(usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ]
        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
            mock_ac.return_value = _FakeStream(chunks)

            collected: list[str] = []
            async for c in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_endpoints={},
                model_params={},
                litellm_kwargs={"api_key": "sk-test"},
                max_iterations=5,
                loop_logger=None,
                vendor="anthropic",
            ):
                collected.append(c)

        # Every text delta is a typed ``chunk`` frame; the stream terminates
        # with a normal ``end`` frame (no stop_reason).
        assert _texts(collected) == ["Hello", ", ", "world!"]
        assert parse_stream_frame(collected[-1]) == {"_mesh_frame": "end"}
        # stream + stream_options were injected
        call_kwargs = mock_ac.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_options"] == {"include_usage": True}

    @pytest.mark.asyncio
    async def test_pops_parallel_tool_calls_from_model_params(self):
        """``parallel_tool_calls`` must NOT reach litellm (Claude rejects it)."""
        from mesh.helpers import _provider_agentic_loop_stream

        chunks = [_chunk(content="ok"), _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1})]
        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
            mock_ac.return_value = _FakeStream(chunks)

            async for _ in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_endpoints={},
                model_params={"parallel_tool_calls": True, "temperature": 0.5},
                litellm_kwargs={},
                vendor="anthropic",
            ):
                pass

        call_kwargs = mock_ac.call_args.kwargs
        assert "parallel_tool_calls" not in call_kwargs
        assert call_kwargs.get("temperature") == 0.5


# ---------------------------------------------------------------------------
# Tool-call iteration followed by text-only iteration
# ---------------------------------------------------------------------------


class TestToolCallIteration:
    @pytest.mark.asyncio
    async def test_preamble_text_yielded_then_tool_runs_then_final_text(self):
        from mesh.helpers import _provider_agentic_loop_stream

        # Iteration 1: text preamble + tool_call.
        tc_first = _tool_call_delta(
            index=0,
            id="call_1",
            type="function",
            name="get_weather",
            arguments='{"city":',
        )
        tc_second = _tool_call_delta(index=0, arguments='"SF"}')
        first_iter = [
            _chunk(content="Let me "),
            _chunk(content="check..."),
            _chunk(tool_calls=[tc_first]),
            _chunk(tool_calls=[tc_second]),
            _chunk(usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ]
        # Iteration 2: pure text final answer.
        second_iter = [
            _chunk(content="It is "),
            _chunk(content="72F."),
            _chunk(usage={"prompt_tokens": 15, "completion_tokens": 4}),
        ]

        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac, patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(return_value=([{"role": "tool", "tool_call_id": "call_1", "content": "sunny"}], [])),
        ) as mock_exec:
            mock_ac.side_effect = [
                _FakeStream(first_iter),
                _FakeStream(second_iter),
            ]

            collected: list[str] = []
            async for c in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "weather?"}],
                tools=[{"type": "function", "function": {"name": "get_weather"}}],
                tool_endpoints={"get_weather": "http://weather"},
                model_params={},
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            ):
                collected.append(c)

        # Preamble live, then tool ran, then final answer streams — all as
        # typed ``chunk`` frames, terminated by a normal ``end`` frame.
        assert _texts(collected) == ["Let me ", "check...", "It is ", "72F."]
        assert parse_stream_frame(collected[-1]) == {"_mesh_frame": "end"}
        assert mock_exec.await_count == 1
        message_arg = mock_exec.await_args.args[0]
        assert message_arg.tool_calls[0].function.name == "get_weather"
        assert message_arg.tool_calls[0].function.arguments == '{"city":"SF"}'
        assert mock_ac.call_count == 2

    @pytest.mark.asyncio
    async def test_parallel_tool_calls_pass_through_to_helper(self):
        from mesh.helpers import _provider_agentic_loop_stream

        tc_a = _tool_call_delta(
            index=0,
            id="call_a",
            type="function",
            name="tool_a",
            arguments="{}",
        )
        tc_b = _tool_call_delta(
            index=1,
            id="call_b",
            type="function",
            name="tool_b",
            arguments="{}",
        )
        first_iter = [
            _chunk(tool_calls=[tc_a]),
            _chunk(tool_calls=[tc_b]),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]
        second_iter = [
            _chunk(content="done"),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]

        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac, patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(
                return_value=(
                    [
                        {"role": "tool", "tool_call_id": "call_a", "content": "A"},
                        {"role": "tool", "tool_call_id": "call_b", "content": "B"},
                    ],
                    [],
                )
            ),
        ) as mock_exec:
            mock_ac.side_effect = [
                _FakeStream(first_iter),
                _FakeStream(second_iter),
            ]

            async for _ in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "do both"}],
                tools=[],
                tool_endpoints={"tool_a": "http://a", "tool_b": "http://b"},
                model_params={"parallel_tool_calls": True},
                litellm_kwargs={},
                vendor="anthropic",
            ):
                pass

        # Parallel flag forwarded to the Phase 1 helper.
        assert mock_exec.await_args.args[2] is True

    @pytest.mark.asyncio
    async def test_accumulated_images_become_user_message_after_tool_results(self):
        """Vendor=openai: image parts are accumulated and injected as a user message."""
        from mesh.helpers import _provider_agentic_loop_stream

        tc = _tool_call_delta(
            index=0,
            id="call_1",
            type="function",
            name="snap",
            arguments="{}",
        )
        first_iter = [
            _chunk(tool_calls=[tc]),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]
        second_iter = [
            _chunk(content="ok"),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]

        image_part = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,abc"},
        }
        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac, patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(
                return_value=(
                    [{"role": "tool", "tool_call_id": "call_1", "content": "[Image]"}],
                    [image_part],
                )
            ),
        ):
            mock_ac.side_effect = [
                _FakeStream(first_iter),
                _FakeStream(second_iter),
            ]

            async for _ in _provider_agentic_loop_stream(
                effective_model="openai/gpt-4o",
                messages=[{"role": "user", "content": "snap please"}],
                tools=[],
                tool_endpoints={"snap": "http://cam"},
                model_params={},
                litellm_kwargs={},
                vendor="openai",
            ):
                pass

        # The second acompletion call's messages should include the
        # synthesized user message with the image_part.
        second_call_messages = mock_ac.call_args_list[1].kwargs["messages"]
        # Find the synthesized user message after the tool message.
        user_messages_after_tool = [
            m
            for m in second_call_messages
            if m.get("role") == "user"
            and isinstance(m.get("content"), list)
            and any(p.get("type") == "image_url" for p in m["content"])
        ]
        assert len(user_messages_after_tool) == 1


# ---------------------------------------------------------------------------
# Max iterations safety net
# ---------------------------------------------------------------------------


class TestMaxIterations:
    @pytest.mark.asyncio
    async def test_emits_terminal_control_frame_when_loop_never_terminates(self):
        from mesh.helpers import _provider_agentic_loop_stream

        # Each iteration always produces a tool_call so the loop never terminates.
        def make_tool_call_iter():
            tc = _tool_call_delta(
                index=0,
                id="call_x",
                type="function",
                name="loop_tool",
                arguments="{}",
            )
            return [
                _chunk(tool_calls=[tc]),
                _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
            ]

        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac, patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(
                return_value=(
                    [{"role": "tool", "tool_call_id": "call_x", "content": "{}"}],
                    [],
                )
            ),
        ):
            mock_ac.side_effect = [_FakeStream(make_tool_call_iter()) for _ in range(2)]

            collected: list[str] = []
            async for c in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "loop"}],
                tools=[],
                tool_endpoints={"loop_tool": "http://x"},
                model_params={},
                litellm_kwargs={},
                max_iterations=2,
                vendor="anthropic",
            ):
                collected.append(c)

        # Issue #1355: the token stream must NOT contain the English marker.
        assert "Maximum tool call iterations reached" not in collected
        assert not any(
            "Maximum tool call iterations" in c for c in collected
        )
        # The stream ends with exactly one typed terminal ``end`` frame
        # carrying the max_iterations stop_reason; no text frames precede it
        # (the model only ever emitted tool calls).
        assert len(collected) == 1
        assert parse_stream_frame(collected[-1]) == {
            "_mesh_frame": "end",
            "stop_reason": "max_iterations",
        }


# ---------------------------------------------------------------------------
# HINT mode: final iteration is buffered, validated, then yielded once
# ---------------------------------------------------------------------------


class TestHintMode:
    @pytest.mark.asyncio
    async def test_hint_mode_buffers_final_iteration_and_yields_once(self):
        """HINT-mode final iteration must NOT yield live mid-stream chunks."""
        from mesh.helpers import _provider_agentic_loop_stream

        # Schema-passing JSON content split across chunks. Without HINT-mode
        # buffering, three live yields would be observed.
        content_chunks = [
            _chunk(content='{"answer":'),
            _chunk(content='"42"'),
            _chunk(content='}'),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]

        # Provider handler signals HINT mode by injecting these flags into
        # model_params (ClaudeHandler.apply_structured_output does this).
        model_params = {
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            "_mesh_hint_fallback_timeout": 30,
            "_mesh_hint_output_type_name": "Answer",
        }

        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
            mock_ac.return_value = _FakeStream(content_chunks)

            collected: list[str] = []
            async for c in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "answer in JSON"}],
                tools=[],
                tool_endpoints={},
                model_params=model_params,
                litellm_kwargs={},
                vendor="anthropic",
            ):
                collected.append(c)

        # Single combined chunk frame, NOT three live deltas; terminated by a
        # normal ``end`` frame.
        assert _texts(collected) == ['{"answer":"42"}']
        assert parse_stream_frame(collected[-1]) == {"_mesh_frame": "end"}

    @pytest.mark.asyncio
    async def test_hint_mode_strips_internal_flags_from_litellm_call(self):
        """``_mesh_*`` flags must be stripped before they reach litellm."""
        from mesh.helpers import _provider_agentic_loop_stream

        content_chunks = [
            _chunk(content='{"a":1}'),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]
        model_params = {
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {"type": "object", "properties": {"a": {"type": "integer"}}},
        }

        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
            mock_ac.return_value = _FakeStream(content_chunks)

            async for _ in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "answer"}],
                tools=[],
                tool_endpoints={},
                model_params=model_params,
                litellm_kwargs={},
                vendor="anthropic",
            ):
                pass

        call_kwargs = mock_ac.call_args.kwargs
        for forbidden in (
            "_mesh_hint_mode",
            "_mesh_hint_schema",
            "_mesh_hint_fallback_timeout",
            "_mesh_hint_output_type_name",
        ):
            assert forbidden not in call_kwargs, (
                f"{forbidden} must be stripped from completion_args"
            )

    @pytest.mark.asyncio
    async def test_hint_fallback_strips_tool_choice_from_base_args(self):
        """Regression guard for PR #1013 review WARNING 2.

        The streaming HINT fallback's ``fallback_base_args`` strip set must
        include ``tool_choice`` (mirroring the buffered path at ~helpers.py:1609
        and the legacy ``process_chat`` path at ~2649). Without this, the
        fallback to ``response_format`` carries a stale ``tool_choice`` from
        the synthetic-tool path, which has no meaning once ``tools`` is gone
        and which some vendors reject.
        """
        from mesh.helpers import _provider_agentic_loop_stream

        # JSON that does NOT parse against the schema so the fallback fires.
        content_chunks = [
            _chunk(content='not json at all'),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]
        model_params = {
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            "_mesh_hint_fallback_timeout": 30,
            "_mesh_hint_output_type_name": "Answer",
            # Pre-existing tool_choice that the synthetic-tool path would
            # have set — must NOT survive into the fallback args.
            "tool_choice": {
                "type": "function",
                "function": {"name": "__mesh_format_response"},
            },
        }

        captured: dict = {}

        async def _capture_fallback(*, base_completion_args, **kwargs):
            captured["base_completion_args"] = base_completion_args
            # Return a passable answer so the loop doesn't blow up.
            return '{"answer":"42"}', None, None

        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac, patch(
            "mesh.helpers._maybe_run_hint_fallback",
            new=AsyncMock(side_effect=_capture_fallback),
        ) as mock_fb:
            mock_ac.return_value = _FakeStream(content_chunks)

            async for _ in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-3-5-haiku",
                messages=[{"role": "user", "content": "answer"}],
                tools=[],
                tool_endpoints={},
                model_params=model_params,
                litellm_kwargs={},
                vendor="anthropic",
            ):
                pass

        assert mock_fb.await_count == 1
        fb_args = captured["base_completion_args"]
        # The critical assertions — all four keys must be stripped, matching
        # the buffered-path strip set.
        assert "tools" not in fb_args
        assert "tool_choice" not in fb_args
        assert "stream" not in fb_args
        assert "stream_options" not in fb_args
