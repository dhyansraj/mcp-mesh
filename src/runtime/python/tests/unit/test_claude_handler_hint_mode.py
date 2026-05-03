"""
Unit tests for ClaudeHandler HINT-mode structured output (issue #820).

Background:
    Anthropic's ``response_format`` path silently hangs (600s+) on certain
    content + tools combinations. ``ClaudeHandler.apply_structured_output``
    used to inherit the base implementation that sets ``response_format``
    directly. We now override it to use HINT mode (prompt injection) plus
    flags that the agentic loop reads to perform a bounded-timeout fallback
    if the HINT response fails to parse.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.engine.provider_handlers.claude_handler import ClaudeHandler
from mesh.helpers import (
    _MESH_HINT_KEYS,
    _extract_text_from_message_content,
    _hint_response_parses,
    _maybe_run_hint_fallback,
    _pop_mesh_hint_flags,
)

# ---------------------------------------------------------------------------
# ClaudeHandler.apply_structured_output
# ---------------------------------------------------------------------------


class TestClaudeApplyStructuredOutputHintMode:
    """Verify the HINT-mode override on ClaudeHandler."""

    def _schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The answer text"},
                "confidence": {"type": "number"},
            },
            "required": ["answer", "confidence"],
        }

    def setup_method(self):
        # Ensure env vars don't leak between tests in this class
        os.environ.pop("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", None)
        os.environ.pop("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT", None)

    def teardown_method(self):
        os.environ.pop("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", None)
        os.environ.pop("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT", None)

    def test_does_not_set_response_format(self):
        """HINT-mode override must NOT set ``response_format``."""
        handler = ClaudeHandler()
        model_params = {
            "messages": [{"role": "system", "content": "You are helpful."}],
        }

        result = handler.apply_structured_output(
            self._schema(), "MyType", model_params
        )

        assert "response_format" not in result, (
            "ClaudeHandler.apply_structured_output must not set response_format "
            "(would re-introduce issue #820 silent hang)"
        )

    def test_sets_hint_mode_flag(self):
        """Internal ``_mesh_hint_mode`` flag must be True after override."""
        handler = ClaudeHandler()
        model_params = {
            "messages": [{"role": "system", "content": "You are helpful."}],
        }

        result = handler.apply_structured_output(
            self._schema(), "MyType", model_params
        )

        assert result.get("_mesh_hint_mode") is True

    def test_sets_hint_schema_flag(self):
        """Sanitized schema must be stashed for the loop to validate against."""
        handler = ClaudeHandler()
        model_params = {
            "messages": [{"role": "system", "content": "You are helpful."}],
        }

        result = handler.apply_structured_output(
            self._schema(), "MyType", model_params
        )

        assert "_mesh_hint_schema" in result
        assert isinstance(result["_mesh_hint_schema"], dict)
        assert result["_mesh_hint_schema"].get("type") == "object"
        assert "answer" in result["_mesh_hint_schema"].get("properties", {})

    def test_sets_fallback_timeout_and_type_name(self):
        """Bounded-timeout + output type name must be stashed for the fallback."""
        handler = ClaudeHandler()
        model_params = {
            "messages": [{"role": "system", "content": "You are helpful."}],
        }

        result = handler.apply_structured_output(
            self._schema(), "MyType", model_params
        )

        assert result.get("_mesh_hint_fallback_timeout") == 90
        assert result.get("_mesh_hint_output_type_name") == "MyType"

    def test_injects_hint_into_system_prompt(self):
        """Override must append an OUTPUT FORMAT block + property names."""
        handler = ClaudeHandler()
        model_params = {
            "messages": [
                {"role": "system", "content": "You are X."},
                {"role": "user", "content": "Hi."},
            ],
        }

        handler.apply_structured_output(self._schema(), "MyType", model_params)

        sys_content = model_params["messages"][0]["content"]
        assert "OUTPUT FORMAT:" in sys_content
        # Schema property names should appear in the example block
        assert "answer" in sys_content
        assert "confidence" in sys_content
        # Original content must be preserved (HINT is appended, not replaced)
        assert sys_content.startswith("You are X.")
        # Non-system messages untouched
        assert model_params["messages"][1]["content"] == "Hi."

    def test_hint_block_appears_only_once_in_first_system_message(self):
        """Only the FIRST system message should be modified (avoid duplication)."""
        handler = ClaudeHandler()
        model_params = {
            "messages": [
                {"role": "system", "content": "First system."},
                {"role": "user", "content": "Hi."},
                {"role": "system", "content": "Second system."},
            ],
        }

        handler.apply_structured_output(self._schema(), "MyType", model_params)

        assert "OUTPUT FORMAT:" in model_params["messages"][0]["content"]
        # Second system message should NOT be modified
        assert model_params["messages"][2]["content"] == "Second system."

    def test_no_handler_instance_state_pollution(self):
        """Singleton handler must not retain per-request schema state.

        ``ProviderHandlerRegistry`` caches one handler instance per vendor.
        If ``apply_structured_output`` stashed schemas on ``self``, concurrent
        requests with different output types would race. Verify no such
        instance attributes are set.
        """
        handler = ClaudeHandler()
        model_params = {
            "messages": [{"role": "system", "content": "X"}],
        }

        handler.apply_structured_output(self._schema(), "MyType", model_params)

        assert not hasattr(handler, "_pending_output_schema"), (
            "ClaudeHandler must not store output schema on the instance "
            "(singleton -> race condition across concurrent requests)"
        )
        assert not hasattr(handler, "_pending_output_type_name"), (
            "ClaudeHandler must not store output type name on the instance "
            "(singleton -> race condition across concurrent requests)"
        )

    def test_force_response_format_env_reverts(self):
        """``MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT=true`` reverts to base behavior."""
        os.environ["MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT"] = "true"
        handler = ClaudeHandler()
        model_params = {
            "messages": [{"role": "system", "content": "You are helpful."}],
        }

        result = handler.apply_structured_output(
            self._schema(), "MyType", model_params
        )

        assert "response_format" in result, (
            "Env override must restore base response_format behavior"
        )
        assert "_mesh_hint_mode" not in result
        assert "_mesh_hint_schema" not in result
        # System message must NOT be mutated by base impl
        assert result["messages"][0]["content"] == "You are helpful."

    def test_force_response_format_env_accepts_aliases(self):
        """Env override accepts common truthy aliases (1, true, yes)."""
        for value in ("1", "true", "TRUE", "yes"):
            os.environ["MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT"] = value
            handler = ClaudeHandler()
            model_params = {
                "messages": [{"role": "system", "content": "X"}],
            }
            result = handler.apply_structured_output(
                self._schema(), "MyType", model_params
            )
            assert "response_format" in result, f"value={value!r} should revert"
            assert "_mesh_hint_mode" not in result


# ---------------------------------------------------------------------------
# _hint_response_parses (helpers.py module-level helper)
# ---------------------------------------------------------------------------


class TestHintResponseParses:
    """Verify the HINT response validator used by the loop's fallback path."""

    def _schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "foo": {"type": "integer"},
            },
            "required": ["foo"],
        }

    def test_valid_json_returns_true(self):
        assert _hint_response_parses('{"foo": 1}', self._schema()) is True

    def test_fenced_json_returns_true(self):
        """``\u0060\u0060\u0060json...\u0060\u0060\u0060`` wrapping must be stripped before parsing."""
        content = '```json\n{"foo": 1}\n```'
        assert _hint_response_parses(content, self._schema()) is True

    def test_plain_fenced_json_returns_true(self):
        """``\u0060\u0060\u0060\\n...\\n\u0060\u0060\u0060`` (no json tag) is also stripped."""
        content = '```\n{"foo": 1}\n```'
        assert _hint_response_parses(content, self._schema()) is True

    def test_invalid_json_returns_false(self):
        assert _hint_response_parses("not json at all", self._schema()) is False

    def test_empty_content_returns_false(self):
        assert _hint_response_parses("", self._schema()) is False

    def test_schema_mismatch_returns_false_when_jsonschema_available(self):
        """Wrong shape (missing required field) fails schema validation."""
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            pytest.skip("jsonschema not installed; structural check is best-effort")

        # Missing required 'foo' key
        assert _hint_response_parses('{"bar": "baz"}', self._schema()) is False

    def test_wrong_type_fails_when_jsonschema_available(self):
        """Type mismatch fails schema validation."""
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            pytest.skip("jsonschema not installed; structural check is best-effort")

        # foo should be integer, got string
        assert _hint_response_parses('{"foo": "not-an-int"}', self._schema()) is False

    def test_extra_whitespace_around_fences_handled(self):
        content = '   ```json\n{"foo": 42}\n```   '
        assert _hint_response_parses(content, self._schema()) is True


# ---------------------------------------------------------------------------
# _pop_mesh_hint_flags — strip helper (issue #820 follow-up)
# ---------------------------------------------------------------------------


class TestPopMeshHintFlags:
    """The strip helper MUST remove every ``_mesh_*`` key before LiteLLM call.

    Background:
        ``ClaudeHandler.apply_structured_output`` sets ``_mesh_hint_*`` flags
        on ``model_params`` so the loop / legacy paths in ``mesh.helpers`` can
        drive a bounded-timeout fallback. These flags MUST be stripped before
        ``litellm.completion(**completion_args)`` — Anthropic rejects unknown
        keys with HTTP 400 ("Extra inputs are not permitted").

        This regression broke 6 tsuite integration tests (tc02, tc04, tc09,
        tc17, tc19, tc23) because the legacy single-call path in
        ``llm_provider`` did NOT strip these flags. This suite locks in the
        helper used by BOTH paths.
    """

    def _full_args(self) -> dict:
        return {
            "model": "anthropic/claude-sonnet-4-5",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [],
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {"type": "object"},
            "_mesh_hint_fallback_timeout": 45,
            "_mesh_hint_output_type_name": "MyResp",
        }

    def test_all_mesh_keys_removed(self):
        args = self._full_args()
        _pop_mesh_hint_flags(args)
        for key in _MESH_HINT_KEYS:
            assert key not in args, (
                f"{key!r} must be stripped before reaching litellm.completion "
                f"(Anthropic rejects with HTTP 400 'Extra inputs are not permitted')"
            )

    def test_returns_captured_values(self):
        args = self._full_args()
        hint_mode, hint_schema, hint_timeout, hint_name = _pop_mesh_hint_flags(args)
        assert hint_mode is True
        assert hint_schema == {"type": "object"}
        assert hint_timeout == 45
        assert hint_name == "MyResp"

    def test_non_mesh_keys_preserved(self):
        args = self._full_args()
        _pop_mesh_hint_flags(args)
        assert args["model"] == "anthropic/claude-sonnet-4-5"
        assert args["messages"] == [{"role": "user", "content": "hi"}]
        assert args["tools"] == []

    def test_defaults_when_keys_absent(self):
        args = {"model": "x", "messages": []}
        hint_mode, hint_schema, hint_timeout, hint_name = _pop_mesh_hint_flags(args)
        assert hint_mode is False
        assert hint_schema is None
        assert hint_timeout == 90  # _DEFAULT_HINT_FALLBACK_TIMEOUT
        assert hint_name == "Response"
        # Original args untouched
        assert args == {"model": "x", "messages": []}

    def test_defaults_override_preserves_loop_state_across_iterations(self):
        """Loop usage: pass current-iteration values as defaults so the
        ``hint_*`` state survives iterations where ``model_params`` no longer
        contains the keys."""
        # First iteration: keys present
        args1 = {
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {"type": "object", "x": 1},
            "_mesh_hint_fallback_timeout": 60,
            "_mesh_hint_output_type_name": "Loop",
        }
        state = _pop_mesh_hint_flags(args1)
        # Second iteration: keys absent — defaults must equal previous state
        args2: dict = {}
        again = _pop_mesh_hint_flags(args2, defaults=state)
        assert again == state

    def test_strip_unblocks_legacy_path_call_args(self):
        """Integration-style: simulate the legacy path's ``completion_args``
        construction and assert post-strip args are safe for LiteLLM."""
        # This mirrors the construction in ``llm_provider``'s legacy path:
        #   completion_args = {model, messages, **litellm_kwargs}
        #   completion_args.update(model_params_copy)  # leaks _mesh_* keys
        litellm_kwargs = {"temperature": 0.7}
        model_params_copy = {
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {"type": "object"},
            "_mesh_hint_fallback_timeout": 30,
            "_mesh_hint_output_type_name": "Resp",
        }
        completion_args = {
            "model": "anthropic/claude-sonnet-4-5",
            "messages": [{"role": "user", "content": "hi"}],
            **litellm_kwargs,
        }
        completion_args.update(model_params_copy)
        # Pre-strip: leak confirmed
        leaked = [k for k in completion_args if k.startswith("_mesh_")]
        assert leaked, "test setup wrong — should have leaked keys"
        # Strip
        _pop_mesh_hint_flags(completion_args)
        # Post-strip: nothing starting with _mesh_ remains
        residual = [k for k in completion_args if k.startswith("_mesh_")]
        assert residual == [], (
            f"Strip did not remove all _mesh_* keys: {residual}. "
            "LiteLLM would reject the request."
        )


# ---------------------------------------------------------------------------
# _extract_text_from_message_content — content normalizer
# ---------------------------------------------------------------------------


class TestExtractTextFromMessageContent:
    """Verify the LiteLLM ``message.content`` normalizer used by both paths."""

    def test_string_passthrough(self):
        assert _extract_text_from_message_content("hello") == "hello"

    def test_none_returns_empty_string(self):
        assert _extract_text_from_message_content(None) == ""

    def test_list_of_dict_blocks_concatenated(self):
        blocks = [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ]
        assert _extract_text_from_message_content(blocks) == "Hello world"

    def test_list_with_none_blocks_skipped(self):
        blocks = [None, {"type": "text", "text": "x"}, None]
        assert _extract_text_from_message_content(blocks) == "x"

    def test_block_with_missing_text_key_treated_as_empty(self):
        blocks = [{"type": "thinking"}, {"type": "text", "text": "ok"}]
        assert _extract_text_from_message_content(blocks) == "ok"

    def test_empty_list_returns_empty_string(self):
        assert _extract_text_from_message_content([]) == ""

    def test_block_with_null_text_value_treated_as_empty(self):
        blocks = [{"type": "text", "text": None}, {"type": "text", "text": "y"}]
        assert _extract_text_from_message_content(blocks) == "y"


# ---------------------------------------------------------------------------
# ClaudeHandler.apply_structured_output — no-system-message synthesis (Fix 1)
# ---------------------------------------------------------------------------


class TestClaudeApplyStructuredOutputNoSystemMessage:
    """Verify HINT-mode synthesizes a system message when none exists.

    Without this, the ``_mesh_hint_*`` flags would be set but the model would
    never see the schema, every response would fail validation, and the 30s
    fallback timeout would fire on every request (issue #820 follow-up).
    """

    def setup_method(self):
        os.environ.pop("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", None)

    def teardown_method(self):
        os.environ.pop("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", None)

    def test_apply_structured_output_synthesizes_system_message_when_none_exists(self):
        """When messages contain no system role, apply_structured_output should
        synthesize one with the HINT block so HINT mode actually works."""
        handler = ClaudeHandler()
        schema = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        }
        model_params = {"messages": [{"role": "user", "content": "Hello"}]}
        handler.apply_structured_output(schema, "MyType", model_params)

        # First message should now be the synthesized system message
        assert model_params["messages"][0]["role"] == "system"
        assert "OUTPUT FORMAT:" in model_params["messages"][0]["content"]
        assert "foo" in model_params["messages"][0]["content"]

        # Original user message should still be there
        assert model_params["messages"][1] == {"role": "user", "content": "Hello"}

        # Flags should be set as normal
        assert model_params["_mesh_hint_mode"] is True
        assert model_params["_mesh_hint_schema"]["properties"]["foo"]["type"] == "string"

    def test_apply_structured_output_synthesizes_when_only_user_messages(self):
        """Multiple user messages, no system — should still prepend exactly one."""
        handler = ClaudeHandler()
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
        model_params = {
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "second"},
            ]
        }
        handler.apply_structured_output(schema, "MyType", model_params)

        # Synthesized system message should be at position 0
        assert model_params["messages"][0]["role"] == "system"
        assert "OUTPUT FORMAT:" in model_params["messages"][0]["content"]
        # Original messages preserved in order after the new system message
        assert model_params["messages"][1] == {"role": "user", "content": "first"}
        assert model_params["messages"][2] == {"role": "assistant", "content": "ok"}
        assert model_params["messages"][3] == {"role": "user", "content": "second"}
        # Only ONE system message synthesized (no duplicates)
        system_count = sum(
            1 for m in model_params["messages"] if m.get("role") == "system"
        )
        assert system_count == 1

    def test_existing_system_message_path_not_affected(self):
        """When a system message already exists, no synthesis happens — the
        existing message is mutated in place (regression check)."""
        handler = ClaudeHandler()
        schema = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        }
        model_params = {
            "messages": [
                {"role": "system", "content": "Original."},
                {"role": "user", "content": "Hi"},
            ]
        }
        handler.apply_structured_output(schema, "MyType", model_params)

        # Length unchanged — no synthesis
        assert len(model_params["messages"]) == 2
        # System content was mutated in place
        assert model_params["messages"][0]["content"].startswith("Original.")
        assert "OUTPUT FORMAT:" in model_params["messages"][0]["content"]


# ---------------------------------------------------------------------------
# _maybe_run_hint_fallback — extracted helper (Fix 3 + Fix 4)
# ---------------------------------------------------------------------------


class TestMaybeRunHintFallback:
    """Verify the extracted fallback helper used by both the agentic loop and
    the legacy single-call path. The helper assumes the caller already
    stripped ``tools`` from ``base_completion_args`` (Fix 4)."""

    @pytest.mark.asyncio
    async def test_returns_unchanged_when_hint_mode_disabled(self):
        """If hint_mode is False, helper is a no-op."""
        result = await _maybe_run_hint_fallback(
            final_content="anything",
            message="msg",
            response="resp",
            base_completion_args={},
            hint_mode=False,
            hint_schema={"type": "object"},
            hint_fallback_timeout=30,
            hint_output_type_name="X",
        )
        assert result == ("anything", "msg", "resp")

    @pytest.mark.asyncio
    async def test_returns_unchanged_when_content_already_parses(self):
        """If hint mode is on but content parses, no fallback fires."""
        schema = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        }
        result = await _maybe_run_hint_fallback(
            final_content='{"foo": "ok"}',
            message="orig_msg",
            response="orig_resp",
            base_completion_args={},
            hint_mode=True,
            hint_schema=schema,
            hint_fallback_timeout=30,
            hint_output_type_name="X",
        )
        assert result == ('{"foo": "ok"}', "orig_msg", "orig_resp")

    @pytest.mark.asyncio
    async def test_strips_no_tools_in_args(self):
        """Helper assumes caller already stripped ``tools``. Verify by
        passing ``base_completion_args`` without ``tools`` and confirming the
        fallback ``litellm.completion`` call doesn't include ``tools`` either
        — proves the helper isn't sneaking it back in."""
        captured_kwargs: dict = {}

        async def fake_to_thread(fn, **kwargs):
            captured_kwargs.update(kwargs)
            fake_msg = MagicMock()
            fake_msg.content = '{"foo": "ok"}'
            fake_response = MagicMock()
            fake_response.choices = [MagicMock(message=fake_msg)]
            return fake_response

        schema = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        }
        base_args = {
            "model": "anthropic/claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "x"}],
        }

        with patch("mesh.helpers.asyncio.to_thread", side_effect=fake_to_thread):
            final_content, _msg, _resp = await _maybe_run_hint_fallback(
                final_content="not parseable as json",
                message=None,
                response=None,
                base_completion_args=base_args,
                hint_mode=True,
                hint_schema=schema,
                hint_fallback_timeout=30,
                hint_output_type_name="MyType",
            )

        # Confirm fallback ran and replaced content
        assert final_content == '{"foo": "ok"}'
        # Tools must NOT have been added by the helper
        assert "tools" not in captured_kwargs
        # response_format and request_timeout must be set by the helper
        assert captured_kwargs["response_format"]["json_schema"]["name"] == "MyType"
        assert captured_kwargs["response_format"]["json_schema"]["strict"] is True
        assert captured_kwargs["request_timeout"] == 30
        # Original base args preserved
        assert captured_kwargs["model"] == "anthropic/claude-3-5-sonnet"

    @pytest.mark.asyncio
    async def test_fallback_failure_re_raises(self):
        """If the fallback litellm call raises, the helper must re-raise
        (caller is responsible for surfacing/wrapping)."""

        async def fake_to_thread(fn, **kwargs):
            raise RuntimeError("simulated litellm failure")

        schema = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
        }
        with patch("mesh.helpers.asyncio.to_thread", side_effect=fake_to_thread):
            with pytest.raises(RuntimeError, match="simulated litellm failure"):
                await _maybe_run_hint_fallback(
                    final_content="not parseable",
                    message=None,
                    response=None,
                    base_completion_args={"model": "x", "messages": []},
                    hint_mode=True,
                    hint_schema=schema,
                    hint_fallback_timeout=30,
                    hint_output_type_name="X",
                )
