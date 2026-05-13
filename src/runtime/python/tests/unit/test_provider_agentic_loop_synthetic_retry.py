"""Unit tests for synthetic-tool corrective-retry in the provider agentic loop.

Issue #961 — when Claude returns malformed ``tool_use.input`` against the
``__mesh_format_response`` schema (the canonical example: the
``{"parameter": {<real fields>}}`` envelope hallucination), the buffered
provider agentic loop performs a single shape-agnostic, schema-driven
corrective retry that mirrors the LiteLLM HINT->``response_format``
fallback in :func:`mesh.helpers._maybe_run_hint_fallback`.

These tests pin down the loop-side behavior. The PR #960 consumer-side
single-key envelope unwrap is covered separately by
``test_response_parser_unwrap.py``; this file is provider-side only.

Mock pattern follows ``test_provider_agentic_loop_synthetic_format.py``
(the local ``_func`` / ``_tool_call`` / ``_message`` / ``_response``
factories are duplicated rather than imported because the source file
keeps them module-private).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _force_litellm_path(monkeypatch):
    """Force the LiteLLM dispatch path for every test in this module.

    The synthetic-tool retry logic is identical on both native and LiteLLM
    paths (the dispatch fork is just where the request is sent). Pinning
    the LiteLLM path lets us mock ``asyncio.to_thread`` directly without
    needing to stand up a fake native handler.
    """
    monkeypatch.setenv("MCP_MESH_NATIVE_LLM", "0")


# ---------------------------------------------------------------------------
# Test fakes (mirrored from test_provider_agentic_loop_synthetic_format.py).
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
    message: MagicMock,
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
) -> MagicMock:
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
    """Synthetic tool with a single-required-field schema.

    The single ``answer`` required field is enough to exercise both the
    pass and fail branches of ``jsonschema.validate``.
    """
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
# Buffered loop: synthetic-tool validation retry
# ---------------------------------------------------------------------------


class TestProviderAgenticLoopSyntheticRetry:
    """Cover the issue #961 corrective-retry path on the buffered provider
    agentic loop. All tests here gate on ``vendor=="anthropic"`` because the
    v1 retry is anthropic-only (see the TODO at the wiring site in
    ``_provider_agentic_loop``).
    """

    @pytest.mark.asyncio
    async def test_retry_fires_on_envelope_shape_and_returns_corrected_args(self):
        """First response wraps the real fields in the well-known
        ``{"parameter": {...}}`` envelope (the exact hallucination shape that
        motivated #961). Schema validation fails, the loop fires the
        corrective retry, the second response returns clean schema-conformant
        args, and that's what the loop surfaces as ``content``.
        """
        from mesh.helpers import _provider_agentic_loop

        bad_args = json.dumps({"parameter": {"answer": "42"}})  # envelope
        good_args = json.dumps({"answer": "42"})  # schema-conformant

        bad_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_bad", SYNTHETIC_TOOL_NAME, bad_args)],
        )
        good_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_good", SYNTHETIC_TOOL_NAME, good_args)],
        )

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=[_response(bad_msg), _response(good_msg)]),
        ) as mock_call:
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "What's the answer?"}],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={"api_key": "sk-test"},
                max_iterations=5,
                vendor="anthropic",
            )

        # Two LLM calls: original + one corrective retry.
        assert mock_call.await_count == 2
        # Final content is the GOOD args, not the envelope-wrapped one.
        assert result["content"] == good_args
        assert json.loads(result["content"]) == {"answer": "42"}

    @pytest.mark.asyncio
    async def test_retry_disabled_when_env_var_zero(self, monkeypatch):
        """``MCP_MESH_LLM_SYNTHETIC_RETRY_MAX=0`` disables the feature
        entirely. The bad args propagate unchanged for the consumer-side
        Pydantic / ResponseParser to handle.
        """
        from mesh.helpers import _provider_agentic_loop

        monkeypatch.setenv("MCP_MESH_LLM_SYNTHETIC_RETRY_MAX", "0")

        bad_args = json.dumps({"parameter": {"answer": "42"}})
        bad_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_bad", SYNTHETIC_TOOL_NAME, bad_args)],
        )

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(bad_msg))
        ) as mock_call:
            result = await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Q?"}],
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={},
                max_iterations=5,
                vendor="anthropic",
            )

        assert mock_call.await_count == 1
        # Bad args propagate unchanged when the retry is disabled.
        assert result["content"] == bad_args

    @pytest.mark.asyncio
    async def test_no_retry_when_first_response_validates(self):
        """Happy path: the first response is schema-conformant, so no retry
        fires and only ONE LLM call is made.
        """
        from mesh.helpers import _provider_agentic_loop

        good_args = json.dumps({"answer": "hello"})
        good_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_ok", SYNTHETIC_TOOL_NAME, good_args)],
        )

        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=_response(good_msg))
        ) as mock_call:
            result = await _provider_agentic_loop(
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

        assert mock_call.await_count == 1
        assert result["content"] == good_args

    @pytest.mark.asyncio
    async def test_retry_also_invalid_returns_second_args_unchanged(self, caplog):
        """When BOTH the original and the corrective-retry call return
        schema-invalid args, the loop returns the second-attempt args
        anyway (the consumer-side ResponseParser is the final salvage gate)
        and emits a WARN for each attempt for observability.
        """
        from mesh.helpers import _provider_agentic_loop

        bad1 = json.dumps({"parameter": {"answer": "x"}})
        bad2 = json.dumps({"input": {"answer": "y"}})
        msg1 = _message(
            content=None,
            tool_calls=[_tool_call("t1", SYNTHETIC_TOOL_NAME, bad1)],
        )
        msg2 = _message(
            content=None,
            tool_calls=[_tool_call("t2", SYNTHETIC_TOOL_NAME, bad2)],
        )

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=[_response(msg1), _response(msg2)]),
        ) as mock_call, caplog.at_level("WARNING", logger="mesh.helpers"):
            result = await _provider_agentic_loop(
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

        assert mock_call.await_count == 2
        # Returned content is the second-attempt args.
        assert result["content"] == bad2

        warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        # Exactly one WARN per attempt — attempt 1 (initial failure) +
        # attempt 2 (still-failed) — both routed through the retry helper.
        assert any("attempt 1" in m for m in warn_msgs), (
            f"Expected attempt-1 WARN; got: {warn_msgs}"
        )
        assert any("attempt 2" in m for m in warn_msgs), (
            f"Expected attempt-2 WARN; got: {warn_msgs}"
        )

    @pytest.mark.asyncio
    async def test_retry_preserves_model_messages_tools_and_forces_synthetic_tool_choice(self):
        """The corrective retry call must preserve model + api_key + the
        augmented tools list, append exactly three new messages (assistant
        bad-turn + tool result + corrective user), and force ``tool_choice``
        to the synthetic tool.
        """
        from mesh.helpers import _provider_agentic_loop

        bad_args = json.dumps({"parameter": {"answer": "x"}})
        good_args = json.dumps({"answer": "x"})
        bad_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_bad", SYNTHETIC_TOOL_NAME, bad_args)],
        )
        good_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_good", SYNTHETIC_TOOL_NAME, good_args)],
        )

        original_messages = [{"role": "user", "content": "Q?"}]

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=[_response(bad_msg), _response(good_msg)]),
        ) as mock_call:
            await _provider_agentic_loop(
                effective_model="anthropic/claude-sonnet-4-5",
                messages=original_messages,
                tools=[],
                tool_endpoints={},
                model_params={
                    "_mesh_synthetic_format_tool_name": SYNTHETIC_TOOL_NAME,
                    "_mesh_synthetic_format_tool": _synthetic_tool(),
                },
                litellm_kwargs={"api_key": "sk-test"},
                max_iterations=5,
                vendor="anthropic",
            )

        assert mock_call.await_count == 2
        first_kwargs = mock_call.await_args_list[0].kwargs
        retry_kwargs = mock_call.await_args_list[1].kwargs

        # Model + api_key preserved across the retry call.
        assert retry_kwargs["model"] == first_kwargs["model"]
        assert retry_kwargs.get("api_key") == first_kwargs.get("api_key")

        # Tools list preserved (synthetic already augmented in the first call,
        # and we want the same augmented list on the retry).
        assert retry_kwargs["tools"] == first_kwargs["tools"]
        retry_tool_names = [t["function"]["name"] for t in retry_kwargs["tools"]]
        assert SYNTHETIC_TOOL_NAME in retry_tool_names

        # Messages: original (1) + assistant-bad-turn (1) + tool-result (1)
        # + corrective-user (1) = 4 messages on the retry call.
        assert len(retry_kwargs["messages"]) == len(first_kwargs["messages"]) + 3
        last_three = retry_kwargs["messages"][-3:]
        assert last_three[0]["role"] == "assistant"
        assert last_three[1]["role"] == "tool"
        assert last_three[1]["tool_call_id"] == "toolu_bad"
        assert last_three[2]["role"] == "user"
        # Corrective prompt mentions the tool name and the explicit
        # "do NOT wrap" instruction.
        corrective_text = last_three[2]["content"]
        assert SYNTHETIC_TOOL_NAME in corrective_text
        assert "envelope" in corrective_text
        assert "schema validation" in corrective_text

        # tool_choice forced to the synthetic tool on retry.
        assert retry_kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": SYNTHETIC_TOOL_NAME},
        }

        # Internal mesh flags MUST NOT leak into the retry call (same
        # invariant as the non-retry path).
        assert "_mesh_synthetic_format_tool" not in retry_kwargs
        assert "_mesh_synthetic_format_tool_name" not in retry_kwargs

    @pytest.mark.asyncio
    async def test_retry_usage_tokens_summed_across_both_calls(self):
        """When BOTH calls report usage, the returned ``_mesh_usage`` block
        sums prompt_tokens and completion_tokens across the original + retry
        calls (so observability captures the corrective call's tokens).
        """
        from mesh.helpers import _provider_agentic_loop

        bad_args = json.dumps({"parameter": {"answer": "x"}})
        good_args = json.dumps({"answer": "x"})
        bad_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_bad", SYNTHETIC_TOOL_NAME, bad_args)],
        )
        good_msg = _message(
            content=None,
            tool_calls=[_tool_call("toolu_good", SYNTHETIC_TOOL_NAME, good_args)],
        )
        # Distinct token counts so the sum is unambiguous.
        bad_resp = _response(bad_msg, prompt_tokens=10, completion_tokens=4)
        good_resp = _response(good_msg, prompt_tokens=20, completion_tokens=8)

        with patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=[bad_resp, good_resp]),
        ):
            result = await _provider_agentic_loop(
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

        usage = result["_mesh_usage"]
        # 10 (original prompt) + 20 (retry prompt) = 30
        assert usage["prompt_tokens"] == 30
        # 4 (original completion) + 8 (retry completion) = 12
        assert usage["completion_tokens"] == 12
        assert usage["model"] == "anthropic/claude-sonnet-4-5"
