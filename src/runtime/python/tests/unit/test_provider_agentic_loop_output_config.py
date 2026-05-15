"""Unit tests for ``_mesh_output_config_mode`` recognition in the buffered
provider agentic loop.

When ClaudeHandler routes a buffered Sonnet 4.5+ / Opus 4.1+ request through
the native ``output_config`` branch, it stamps ``_mesh_output_config_mode``
on ``model_params``. The loop must:

  1. Pop the sentinel before reaching ``litellm.completion`` (otherwise
     Anthropic rejects the request with HTTP 400).
  2. On the "no tool calls" branch (the model returned a plain TextBlock —
     which IS the structured answer), short-circuit synthetic-fallback
     recovery and return the text content directly.

Companion handler-side tests live in
``_mcp_mesh/engine/provider_handlers/tests/test_claude_handler_output_config.py``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _force_litellm_path(monkeypatch):
    """Force the LiteLLM path so we can mock ``asyncio.to_thread`` directly.

    The output_config sentinel pop / short-circuit logic runs on both the
    native and LiteLLM dispatch paths (same agentic loop). Mocking the
    LiteLLM path keeps the tests independent of the anthropic SDK install
    state.
    """
    monkeypatch.setenv("MCP_MESH_NATIVE_LLM", "0")


# ---------------------------------------------------------------------------
# Test fakes (mirror the synthetic-format tests)
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


def _response(
    message: MagicMock, prompt_tokens: int = 5, completion_tokens: int = 3
) -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message = message
    resp.choices = [choice]
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    resp.usage = usage
    resp.model = "claude-sonnet-4-6"
    return resp


def _trip_schema() -> dict:
    """A real schema so the defense-in-depth parse check has something to
    validate against."""
    return {
        "type": "object",
        "properties": {
            "destination": {"type": "string"},
            "days": {"type": "integer"},
        },
        "required": ["destination", "days"],
        "additionalProperties": False,
    }


class TestOutputConfigModeNoToolCalls:
    """When the loop receives a no-tool-calls response AND the
    ``_mesh_output_config_mode`` sentinel is True, it MUST:
      * skip synthetic-fallback recovery
      * return the text content as the final answer
    """

    @pytest.mark.asyncio
    async def test_output_config_mode_returns_text_directly_no_fallback(self):
        """The canonical happy path: Anthropic returned a structured JSON
        TextBlock; the loop returns it as ``message_dict["content"]`` without
        calling ``_maybe_run_synthetic_fallback``.
        """
        from mesh.helpers import _provider_agentic_loop

        # The model returned the structured answer as plain text (no
        # tool_calls).
        answer = json.dumps({"destination": "Paris", "days": 5})
        msg = _message(content=answer, tool_calls=None)

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(msg))
        ), patch(
            "mesh.helpers._maybe_run_synthetic_fallback",
            new=AsyncMock(),
        ) as mock_synth_fb, patch(
            "mesh.helpers._maybe_run_hint_fallback",
            new=AsyncMock(),
        ) as mock_hint_fb:
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-6",
                messages=[
                    {"role": "user", "content": "Plan a 5-day Paris trip."}
                ],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_output_config_mode": True,
                    "_mesh_output_config_schema": _trip_schema(),
                    "_mesh_output_config_output_type_name": "Trip",
                    # ``response_format`` would normally be set by the
                    # handler; not strictly needed for this loop-side test.
                },
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            )

        # Final content is the model's text answer verbatim.
        assert result["content"] == answer
        assert json.loads(result["content"]) == {
            "destination": "Paris",
            "days": 5,
        }
        # Usage metadata flows through unchanged.
        assert result["_mesh_usage"]["prompt_tokens"] == 5
        assert result["_mesh_usage"]["completion_tokens"] == 3

        # CRUCIAL: neither fallback was invoked — output_config mode bypasses
        # both synthetic-tool and HINT recovery paths.
        mock_synth_fb.assert_not_called()
        mock_hint_fb.assert_not_called()

    @pytest.mark.asyncio
    async def test_output_config_mode_sentinel_stripped_before_wire_call(self):
        """The ``_mesh_output_config_*`` keys MUST be popped before reaching
        ``litellm.completion`` (otherwise Anthropic rejects with HTTP 400
        "Extra inputs are not permitted").
        """
        from mesh.helpers import _provider_agentic_loop

        answer = json.dumps({"destination": "Tokyo", "days": 7})
        msg = _message(content=answer, tool_calls=None)
        mock_completion = AsyncMock(return_value=_response(msg))

        with patch("asyncio.to_thread", new=mock_completion):
            await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Plan a Tokyo trip."}],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_output_config_mode": True,
                    "_mesh_output_config_schema": _trip_schema(),
                    "_mesh_output_config_output_type_name": "Trip",
                },
                litellm_kwargs={},
                vendor="anthropic",
            )

        # Inspect the kwargs handed to ``litellm.completion`` — none of the
        # ``_mesh_output_config_*`` sentinels should be present.
        call_kwargs = mock_completion.await_args.kwargs
        assert "_mesh_output_config_mode" not in call_kwargs
        assert "_mesh_output_config_schema" not in call_kwargs
        assert "_mesh_output_config_output_type_name" not in call_kwargs

    @pytest.mark.asyncio
    async def test_output_config_mode_off_falls_through_to_existing_fallbacks(self):
        """When ``_mesh_output_config_mode`` is False / absent, the existing
        synthetic-fallback machinery still runs on the "no tool calls"
        branch — guarding against accidentally bypassing recovery on the
        synthetic-tool path.
        """
        from mesh.helpers import _provider_agentic_loop

        msg = _message(content="some text", tool_calls=None)

        # Make the synthetic fallback a no-op pass-through so we can assert
        # it WAS invoked.
        async def _passthrough_synth(
            *, final_content, message, response, **kwargs
        ):
            return final_content, message, response

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(msg))
        ), patch(
            "mesh.helpers._maybe_run_synthetic_fallback",
            new=AsyncMock(side_effect=_passthrough_synth),
        ) as mock_synth_fb:
            await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[],
                tool_endpoints={},
                model_params={
                    # No output_config sentinel.
                },
                litellm_kwargs={},
                vendor="anthropic",
            )

        # Synthetic-fallback helper was reached — output_config short-circuit
        # only fires when the sentinel is True.
        mock_synth_fb.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_config_mode_logs_warning_on_unparseable_text(
        self, caplog
    ):
        """Defense-in-depth: when the model's text doesn't parse against the
        captured schema, the loop logs a WARN but does NOT retry — the
        framework principle is "don't force the model after it has answered".
        """
        from mesh.helpers import _provider_agentic_loop

        # Plain text — not valid JSON for the schema.
        unparseable = "I cannot plan that trip."
        msg = _message(content=unparseable, tool_calls=None)

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(msg))
        ), patch(
            "mesh.helpers._maybe_run_synthetic_fallback",
            new=AsyncMock(),
        ) as mock_synth_fb:
            with caplog.at_level("WARNING", logger="mesh.helpers"):
                result = await _provider_agentic_loop(
                    effective_model="anthropic/claude-sonnet-4-6",
                    messages=[{"role": "user", "content": "Q?"}],
                    tools=[],
                    tool_endpoints={},
                    model_params={
                        "_mesh_output_config_mode": True,
                        "_mesh_output_config_schema": _trip_schema(),
                        "_mesh_output_config_output_type_name": "Trip",
                    },
                    litellm_kwargs={},
                    vendor="anthropic",
                    loop_logger=__import__("logging").getLogger("mesh.helpers"),
                )

        # Raw text is returned verbatim — no retry, no fallback.
        assert result["content"] == unparseable
        mock_synth_fb.assert_not_called()
        # WARN was logged about the parse failure.
        warn_msgs = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert any(
            "output_config mode" in m and "did not parse" in m
            for m in warn_msgs
        ), f"Expected parse-warning; got: {warn_msgs}"


class TestOutputConfigModeWithToolCalls:
    """A model that returns ``tool_calls`` in ``output_config`` mode is
    unexpected — but the loop's existing tool-execution branch should still
    handle it (no special-casing). This guards against the new short-circuit
    accidentally affecting the tool-calls path."""

    @pytest.mark.asyncio
    async def test_output_config_mode_does_not_intercept_real_tool_call(self):
        """When the model emits a real tool call mid-loop (rare under
        output_config, but possible if real tools are in the request), the
        loop must execute the tool and continue — not short-circuit on the
        text content (which is empty)."""
        from mesh.helpers import _provider_agentic_loop

        # Iter 1: real tool call. Iter 2: structured text answer.
        tool_call_msg = _message(
            content=None,
            tool_calls=[_tool_call("call_real", "get_weather", '{"city":"NYC"}')],
        )
        final_msg = _message(
            content=json.dumps({"destination": "NYC", "days": 3}),
            tool_calls=None,
        )

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(
                side_effect=[_response(tool_call_msg), _response(final_msg)]
            ),
        ), patch(
            "mesh.helpers._execute_tool_calls_for_iteration",
            new=AsyncMock(
                return_value=(
                    [
                        {
                            "role": "tool",
                            "tool_call_id": "call_real",
                            "content": "sunny",
                        }
                    ],
                    [],
                )
            ),
        ) as mock_exec:
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Plan a NYC trip."}],
                tools=[
                    {"type": "function", "function": {"name": "get_weather"}}
                ],
                tool_endpoints={"get_weather": "http://weather"},
                model_params={
                    "_mesh_output_config_mode": True,
                    "_mesh_output_config_schema": _trip_schema(),
                    "_mesh_output_config_output_type_name": "Trip",
                },
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            )

        # Real tool executed between iter 1 and iter 2.
        assert mock_exec.await_count == 1
        # Final content is iter 2's structured text.
        assert json.loads(result["content"]) == {"destination": "NYC", "days": 3}


class TestOutputConfigShortCircuitContentFallback:
    """Regression guard for PR #1013 review WARNING 1.

    The output_config short-circuit emits ``content: final_content``. If the
    text-extractor returns ``None`` (rare partial-block case) the legacy
    ``process_chat`` path (~helpers.py:2702) explicitly substitutes ``""``;
    the short-circuit must do the same so downstream consumers never see
    ``content: None``.
    """

    @pytest.mark.asyncio
    async def test_short_circuit_substitutes_empty_string_when_extractor_returns_none(
        self,
    ):
        """When ``_extract_text_from_message_content`` returns ``None`` the
        ``message_dict["content"]`` must be ``""`` not ``None``."""
        from mesh.helpers import _provider_agentic_loop

        # The model returned no parsable text — extractor will yield None.
        msg = _message(content=None, tool_calls=None)

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(msg))
        ), patch(
            "mesh.helpers._extract_text_from_message_content",
            return_value=None,
        ), patch(
            "mesh.helpers._maybe_run_synthetic_fallback",
            new=AsyncMock(),
        ), patch(
            "mesh.helpers._maybe_run_hint_fallback",
            new=AsyncMock(),
        ):
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_output_config_mode": True,
                    "_mesh_output_config_schema": _trip_schema(),
                    "_mesh_output_config_output_type_name": "Trip",
                },
                litellm_kwargs={},
                vendor="anthropic",
            )

        # The critical assertion: never ``None``, always ``""``.
        assert result["content"] == ""
        assert result["content"] is not None
