"""Unit tests for synthetic-format-tool integration in the provider agentic loops.

Issue #834: PR refactor — native Anthropic SDK structured output via the
synthetic-tool pattern (``__mesh_format_response``) with ``tool_choice="auto"``.
The flow:

  1. ``ClaudeHandler.apply_structured_output`` (native path) stamps
     ``_mesh_synthetic_format_tool``/``_mesh_synthetic_format_tool_name`` into
     model_params.
  2. The agentic loop in ``mesh.helpers`` pops the flag, appends the synthetic
     tool to the tools list, sets ``tool_choice="auto"`` (or forces it when
     there are no real user tools), and recognizes a tool_call to that name as
     the model's "I'm done — here's the structured answer" signal.

These tests pin down the loop-side behavior. The handler-side tests live in
``_mcp_mesh/engine/provider_handlers/tests/test_claude_handler_native.py``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _force_litellm_path(monkeypatch):
    """Force the LiteLLM path for every test in this module.

    Issue #834 flipped MCP_MESH_NATIVE_LLM from opt-in to opt-out. These
    tests verify the agentic loop's synthetic-tool recognition by mocking
    ``litellm.completion`` / ``litellm.acompletion`` directly, so they
    must explicitly disable native dispatch — the synthetic-tool sentinels
    are stamped by the handler and the loop's recognition logic is
    identical on both paths.
    """
    monkeypatch.setenv("MCP_MESH_NATIVE_LLM", "0")


# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------


def _func(name: str, arguments: str) -> MagicMock:
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments
    return fn


def _tool_call(id: str, name: str, arguments: str) -> MagicMock:
    tc = MagicMock()
    tc.id = id
    tc.type = "function"
    tc.function = _func(name, arguments)
    return tc


def _message(content: str | None, tool_calls: list | None = None) -> MagicMock:
    m = MagicMock()
    m.content = content
    m.role = "assistant"
    m.tool_calls = tool_calls
    return m


def _response(message: MagicMock, prompt_tokens: int = 5, completion_tokens: int = 3) -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message = message
    resp.choices = [choice]
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    resp.usage = usage
    resp.model = "claude-sonnet-4-5"
    return resp


SYNTHETIC_TOOL_NAME = "__mesh_format_response"


def _synthetic_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": SYNTHETIC_TOOL_NAME,
            "description": "synthetic format tool",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    }


# ---------------------------------------------------------------------------
# Buffered loop: _provider_agentic_loop
# ---------------------------------------------------------------------------


class TestBufferedLoopSyntheticRecognition:
    @pytest.mark.asyncio
    async def test_synthetic_tool_call_terminates_loop_and_returns_json_content(self):
        """A tool_call to ``__mesh_format_response`` is recognized as the
        final answer. Its arguments become ``message_dict["content"]``.
        """
        from mesh.helpers import _provider_agentic_loop

        # The model calls ONLY the synthetic tool — its args are the answer.
        synth_args = json.dumps({"answer": "42"})
        msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_1", SYNTHETIC_TOOL_NAME, synth_args)],
        )

        with patch("asyncio.to_thread", new=AsyncMock(return_value=_response(msg))):
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "What's the answer?"}],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                    "_mesh_synthetic_format_output_type_name": "Answer",
                },
                litellm_kwargs={"api_key": "sk-test"},
                max_iterations=5,
                vendor="anthropic",
            )

        assert result["content"] == synth_args
        assert json.loads(result["content"]) == {"answer": "42"}
        # Usage metadata flows through unchanged.
        assert result["_mesh_usage"]["prompt_tokens"] == 5
        assert result["_mesh_usage"]["completion_tokens"] == 3

    @pytest.mark.asyncio
    async def test_real_tool_call_continues_loop_normally(self):
        """A tool_call to a REAL user tool still triggers the existing
        execute-tool-then-iterate path. Synthetic recognition must NOT
        intercept real tool calls.
        """
        from mesh.helpers import _provider_agentic_loop

        # Iter 1: model calls real tool 'get_weather'.
        # Iter 2: model calls synthetic with the structured answer.
        real_msg = _message(
            content=None,
            tool_calls=[_tool_call("call_real", "get_weather", '{"city":"SF"}')],
        )
        synth_msg = _message(
            content=None,
            tool_calls=[
                _tool_call("call_synth", SYNTHETIC_TOOL_NAME, '{"answer":"sunny"}')
            ],
        )

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=[_response(real_msg), _response(synth_msg)]),
        ), patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(return_value=([{"role": "tool", "tool_call_id": "call_real", "content": "sunny"}], [])),
        ) as mock_exec:
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Weather in SF?"}],
                tools=[{"type": "function", "function": {"name": "get_weather"}}],
                tool_endpoints={"get_weather": "http://weather"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                    "_mesh_synthetic_format_output_type_name": "Answer",
                },
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            )

        # Real tool was executed once (between iter 1 and iter 2).
        assert mock_exec.await_count == 1
        # Final content is the synthetic args from iter 2.
        assert json.loads(result["content"]) == {"answer": "sunny"}

    @pytest.mark.asyncio
    async def test_synthetic_wins_when_both_real_and_synthetic_in_same_turn(self):
        """When the model emits BOTH a real tool call AND the synthetic in the
        same iteration, the synthetic wins — the model has signaled "I'm done"
        and executing real tools would imply another iteration the model
        already opted out of. Documented behavior.
        """
        from mesh.helpers import _provider_agentic_loop

        msg = _message(
            content=None,
            tool_calls=[
                _tool_call("call_real", "get_weather", '{"city":"NYC"}'),
                _tool_call("call_synth", SYNTHETIC_TOOL_NAME, '{"answer":"done"}'),
            ],
        )

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(msg))
        ), patch(
            "mesh.helpers._execute_tool_calls_for_iteration", new=AsyncMock()
        ) as mock_exec:
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[{"type": "function", "function": {"name": "get_weather"}}],
                tool_endpoints={"get_weather": "http://weather"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                vendor="anthropic",
            )

        assert json.loads(result["content"]) == {"answer": "done"}
        # Real tool was NOT executed — synthetic short-circuits.
        mock_exec.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_synthetic_tool_appended_to_completion_args_tools_list(self):
        """Verify the synthetic tool actually gets injected into the request
        going to the LLM. This catches a class of regression where the flag
        is read but never spliced into the tools list.
        """
        from mesh.helpers import _provider_agentic_loop

        msg = _message(
            content=None,
            tool_calls=[_tool_call("t", SYNTHETIC_TOOL_NAME, "{}")],
        )

        with patch("asyncio.to_thread", new=AsyncMock(return_value=_response(msg))) as mock_call:
            await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[{"type": "function", "function": {"name": "real_tool"}}],
                tool_endpoints={"real_tool": "http://x"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                vendor="anthropic",
            )

        sent = mock_call.await_args.kwargs
        tool_names = [t["function"]["name"] for t in sent["tools"]]
        assert "real_tool" in tool_names
        assert SYNTHETIC_TOOL_NAME in tool_names
        # tool_choice is "auto" because real tools are present.
        assert sent["tool_choice"] == "auto"
        # Internal flags must NOT leak to the API.
        assert "_mesh_synthetic_format_tool" not in sent
        assert "_mesh_synthetic_format_tool_name" not in sent

    @pytest.mark.asyncio
    async def test_no_real_tools_forces_synthetic_tool_choice(self):
        """Zero real tools → tool_choice forced to the synthetic tool. Saves a
        round-trip; deterministic single call. Mirrors TS/Java perf logic.
        """
        from mesh.helpers import _provider_agentic_loop

        msg = _message(
            content=None,
            tool_calls=[_tool_call("t", SYNTHETIC_TOOL_NAME, "{}")],
        )

        with patch("asyncio.to_thread", new=AsyncMock(return_value=_response(msg))) as mock_call:
            await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                vendor="anthropic",
            )

        sent = mock_call.await_args.kwargs
        assert sent["tool_choice"] == {
            "type": "function",
            "function": {"name": SYNTHETIC_TOOL_NAME},
        }

    @pytest.mark.asyncio
    async def test_max_iterations_exhausted_without_synthetic_returns_safety_message(self):
        """If the model NEVER calls the synthetic and instead keeps calling
        real tools, the loop hits ``max_iterations`` and returns the safety
        text. Should NOT infinite-loop.
        """
        from mesh.helpers import _provider_agentic_loop

        # Every iteration returns a real tool call (model never signals done).
        real_msg = _message(
            content=None,
            tool_calls=[_tool_call("call_real", "get_weather", '{}')],
        )

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(return_value=_response(real_msg)),
        ), patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(return_value=([{"role": "tool", "tool_call_id": "call_real", "content": "x"}], [])),
        ):
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[{"type": "function", "function": {"name": "get_weather"}}],
                tool_endpoints={"get_weather": "http://x"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                max_iterations=3,
                vendor="anthropic",
            )

        assert "Maximum tool call iterations" in result["content"]


# ---------------------------------------------------------------------------
# Streaming loop: _provider_agentic_loop_stream
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


def _tc_delta(
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
    """Minimal async iterator for streaming responses (with aclose)."""

    def __init__(self, chunks: list):
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


class TestStreamingLoopSyntheticRecognition:
    @pytest.mark.asyncio
    async def test_synthetic_tool_emits_one_content_chunk_with_json(self):
        """When the streamed tool_call merges to the synthetic tool name, the
        loop emits ONE final content chunk carrying the JSON arguments — not
        the tool_use deltas.
        """
        from mesh.helpers import _provider_agentic_loop_stream

        chunks = [
            _chunk(model="claude-sonnet-4-5"),
            _chunk(
                tool_calls=[
                    _tc_delta(
                        index=0,
                        id="toolu_xyz",
                        type="function",
                        name=SYNTHETIC_TOOL_NAME,
                    )
                ]
            ),
            _chunk(tool_calls=[_tc_delta(index=0, arguments='{"answer":')]),
            _chunk(tool_calls=[_tc_delta(index=0, arguments='"hello"}')]),
            _chunk(usage={"prompt_tokens": 10, "completion_tokens": 4}),
        ]
        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
            mock_ac.return_value = _FakeStream(chunks)

            collected: list[str] = []
            async for c in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[{"type": "function", "function": {"name": "real_tool"}}],
                tool_endpoints={"real_tool": "http://x"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            ):
                collected.append(c)

        # Exactly one chunk: the JSON arguments string.
        assert len(collected) == 1
        assert json.loads(collected[0]) == {"answer": "hello"}

    @pytest.mark.asyncio
    async def test_real_tool_call_still_executes_then_continues(self):
        """A streamed tool_use to a REAL user tool must still trigger the
        existing execute-tool-then-iterate path. Synthetic recognition must
        NOT swallow real tool calls.
        """
        from mesh.helpers import _provider_agentic_loop_stream

        # Iter 1: real tool call.
        first = [
            _chunk(
                tool_calls=[
                    _tc_delta(
                        index=0,
                        id="call_real",
                        type="function",
                        name="get_weather",
                    )
                ]
            ),
            _chunk(tool_calls=[_tc_delta(index=0, arguments='{"city":"SF"}')]),
            _chunk(usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ]
        # Iter 2: synthetic emits the structured answer.
        second = [
            _chunk(
                tool_calls=[
                    _tc_delta(
                        index=0,
                        id="call_synth",
                        type="function",
                        name=SYNTHETIC_TOOL_NAME,
                    )
                ]
            ),
            _chunk(tool_calls=[_tc_delta(index=0, arguments='{"answer":"sunny"}')]),
            _chunk(usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ]
        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac, patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(
                return_value=(
                    [{"role": "tool", "tool_call_id": "call_real", "content": "sunny"}],
                    [],
                )
            ),
        ) as mock_exec:
            mock_ac.side_effect = [_FakeStream(first), _FakeStream(second)]

            collected: list[str] = []
            async for c in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Weather?"}],
                tools=[{"type": "function", "function": {"name": "get_weather"}}],
                tool_endpoints={"get_weather": "http://x"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            ):
                collected.append(c)

        # Real tool was executed.
        assert mock_exec.await_count == 1
        # Final emitted chunk is the synthetic JSON.
        assert len(collected) == 1
        assert json.loads(collected[0]) == {"answer": "sunny"}

    @pytest.mark.asyncio
    async def test_synthetic_tool_in_request_tools_list(self):
        """Verify the synthetic tool is injected into the streaming request
        sent to litellm. ``tool_choice`` is ``"auto"`` when real tools exist.
        """
        from mesh.helpers import _provider_agentic_loop_stream

        chunks = [
            _chunk(
                tool_calls=[
                    _tc_delta(
                        index=0,
                        id="t",
                        type="function",
                        name=SYNTHETIC_TOOL_NAME,
                    )
                ]
            ),
            _chunk(tool_calls=[_tc_delta(index=0, arguments="{}")]),
            _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
        ]
        with patch("litellm.acompletion", new=AsyncMock()) as mock_ac:
            mock_ac.return_value = _FakeStream(chunks)

            async for _ in _provider_agentic_loop_stream(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[{"type": "function", "function": {"name": "real_tool"}}],
                tool_endpoints={"real_tool": "http://x"},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                vendor="anthropic",
            ):
                pass

        sent = mock_ac.call_args.kwargs
        tool_names = [t["function"]["name"] for t in sent["tools"]]
        assert "real_tool" in tool_names
        assert SYNTHETIC_TOOL_NAME in tool_names
        assert sent["tool_choice"] == "auto"
        # Mesh internal flags MUST NOT reach the wire.
        assert "_mesh_synthetic_format_tool" not in sent
        assert "_mesh_synthetic_format_tool_name" not in sent
