"""Issue #1162 findings 3 and 4.

Finding 3 (LOW/MED): a final assistant message with ``content: null`` is a
legal OpenAI-shape response (e.g. max-token cutoffs). It must not raise
TypeError from the debug-log slice or from the parser:

* ``output_type=str`` → the call returns ``""``;
* Pydantic output → the rich ``ResponseParseError`` is raised with a clear
  "empty content" message.

Finding 4 (LOW): there used to be TWO ``ResponseParseError`` classes — a rich
one in ``llm_errors`` (raw_content / expected_schema / validation_errors)
that was imported and caught, and a bare one in ``response_parser`` that was
actually raised. ``except llm_errors.ResponseParseError`` silently missed
real parse failures. Now there is exactly one class: the parser raises the
rich one and ``response_parser.ResponseParseError`` is a back-compat alias.
"""

import json

import pytest
from _mcp_mesh.engine import llm_errors, response_parser
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent, _MockMessage, _dumps_safe
from _mcp_mesh.engine.response_parser import ResponseParser
from pydantic import BaseModel


class StrictModel(BaseModel):
    count: int
    name: str


def _make_agent(provider_proxy, output_type) -> MeshLlmAgent:
    return MeshLlmAgent(
        config=LLMConfig(
            provider={"capability": "llm", "tags": ["claude"]},
            model=None,
            max_iterations=3,
            system_prompt="Test prompt",
        ),
        filtered_tools=[],
        output_type=output_type,
        provider_proxy=provider_proxy,
        vendor="anthropic",
    )


async def _none_content_provider(request):
    return {"role": "assistant", "content": None}


async def _dict_content_provider(request):
    return {"role": "assistant", "content": {"count": 7, "name": "ok"}}


async def _error_map_provider(request):
    return {"error": "rate limited by vendor"}


async def _bare_answer_provider(request):
    return {"verdict": "BLOCK", "reason": "policy violation", "count": 1, "name": "x"}


class TestContentNoneFinalResponse:
    @pytest.mark.asyncio
    async def test_str_output_returns_empty_string(self):
        agent = _make_agent(_none_content_provider, str)
        result = await agent("hello")
        assert result == ""

    @pytest.mark.asyncio
    async def test_pydantic_output_raises_rich_parse_error(self):
        agent = _make_agent(_none_content_provider, StrictModel)
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            await agent("hello")
        err = exc_info.value
        assert err.expected_schema == "StrictModel"
        assert "empty content" in (err.validation_errors or "")

    def test_parse_response_none_str_output(self):
        agent = _make_agent(_none_content_provider, str)
        assert agent._parse_response(None) == ""

    def test_parse_response_none_pydantic_output(self):
        agent = _make_agent(_none_content_provider, StrictModel)
        with pytest.raises(llm_errors.ResponseParseError):
            agent._parse_response(None)


class TestMockMessageContentRecovery:
    """Consumer-side recovery of malformed-but-recoverable content shapes."""

    def test_string_content_unchanged(self):
        msg = _MockMessage({"role": "assistant", "content": "hello"})
        assert msg.content == "hello"

    def test_dict_content_serialized_to_json_string(self):
        msg = _MockMessage(
            {"role": "assistant", "content": {"count": 5, "name": "x"}}
        )
        assert msg.content == json.dumps({"count": 5, "name": "x"})

    def test_bare_map_without_content_or_role_serialized_whole(self):
        msg = _MockMessage({"count": 5, "name": "x"})
        assert msg.content == json.dumps({"count": 5, "name": "x"})

    def test_envelope_with_none_content_stays_none(self):
        # A real envelope (has "role") with null content is legal — left as-is.
        msg = _MockMessage({"role": "assistant", "content": None})
        assert msg.content is None

    def test_error_map_not_treated_as_bare_answer(self):
        # {"error": <truthy>} is a non-answer payload — must NOT be serialized as
        # content (would produce a misleading schema failure). Left empty so the
        # empty-content diagnostic surfaces the error.
        msg = _MockMessage({"error": "rate limited by vendor"})
        assert msg.content is None

    def test_bare_answer_with_null_error_field_recovered(self):
        # "error": null is a plain model field, not a failure payload — the map
        # is still a genuine bare answer and must be recovered.
        payload = {"data": "ok", "error": None, "count": 1, "name": "x"}
        msg = _MockMessage(payload)
        assert msg.content == _dumps_safe(payload)

    def test_non_serializable_leaf_does_not_abort(self):
        # A stray non-JSON leaf must be coerced (default=str), not raise.
        from datetime import datetime

        payload = {"when": datetime(2026, 7, 2), "count": 1, "name": "x"}
        msg = _MockMessage(payload)
        assert isinstance(msg.content, str)
        assert "2026" in msg.content

    def test_mesh_usage_only_map_not_treated_as_bare_answer(self):
        msg = _MockMessage({"_mesh_usage": {"prompt_tokens": 1}})
        assert msg.content is None

    def test_tool_calls_only_map_not_treated_as_bare_answer_no_crash(self):
        # A tool-call turn without role/content must not be dumped as the answer,
        # and its tool_calls must still parse.
        msg = _MockMessage(
            {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    }
                ]
            }
        )
        assert msg.content is None
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    def test_malformed_tool_calls_entry_ignored_not_crash(self):
        # An entry missing "id"/"function" is skipped rather than raising KeyError.
        msg = _MockMessage(
            {"role": "assistant", "content": "hi", "tool_calls": [{"name": "f"}]}
        )
        assert msg.content == "hi"
        assert msg.tool_calls is None


class TestDictContentEndToEnd:
    @pytest.mark.asyncio
    async def test_dict_content_parses_into_model(self):
        agent = _make_agent(_dict_content_provider, StrictModel)
        result = await agent("hello")
        assert result.count == 7
        assert result.name == "ok"

    @pytest.mark.asyncio
    async def test_genuine_bare_answer_recovered(self):
        # A genuinely bare answer map (no envelope-adjacent keys) is recovered.
        agent = _make_agent(_bare_answer_provider, StrictModel)
        result = await agent("hello")
        assert result.count == 1
        assert result.name == "x"

    @pytest.mark.asyncio
    async def test_error_map_surfaces_error_in_diagnostic_not_schema_failure(self):
        agent = _make_agent(_error_map_provider, StrictModel)
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            await agent("hello")
        err = exc_info.value
        assert "empty content" in (err.validation_errors or "")
        # The real error payload is visible in the raw-payload snippet.
        assert "rate limited by vendor" in err.raw_content


class TestEmptyContentRawPayloadDiagnostic:
    def test_parse_response_includes_raw_payload(self):
        agent = _make_agent(_none_content_provider, StrictModel)
        raw = _MockMessage({"role": "assistant", "content": None})
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            agent._parse_response(None, raw_response=raw)
        err = exc_info.value
        assert "assistant" in err.raw_content
        assert "empty content" in (err.validation_errors or "")

    def test_empty_string_content_pydantic_raises(self):
        agent = _make_agent(_none_content_provider, StrictModel)
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            agent._parse_response("")
        assert "empty content" in (exc_info.value.validation_errors or "")

    def test_empty_string_content_str_output_returns_empty(self):
        agent = _make_agent(_none_content_provider, str)
        assert agent._parse_response("") == ""

    def test_raw_payload_non_serializable_still_useful(self):
        # A non-JSON leaf in the raw payload must not collapse the snippet to an
        # object repr — _dumps_safe coerces it (default=str) so the diagnostic
        # still summarizes the payload.
        from datetime import datetime

        agent = _make_agent(_none_content_provider, StrictModel)
        raw = _MockMessage(
            {"role": "assistant", "content": None, "when": datetime(2026, 7, 2)}
        )
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            agent._parse_response(None, raw_response=raw)
        err = exc_info.value
        assert "2026" in err.raw_content
        assert "object at 0x" not in err.raw_content


class TestResponseParseErrorUnification:
    def test_single_class_aliased_for_back_compat(self):
        """The bare class in response_parser is gone; the import path still
        works and resolves to the rich llm_errors class."""
        assert response_parser.ResponseParseError is llm_errors.ResponseParseError

    def test_invalid_json_raises_llm_errors_class_with_attrs(self):
        raw = "definitely not json"
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            ResponseParser.parse(raw, StrictModel)
        err = exc_info.value
        assert err.raw_content == raw
        assert err.expected_schema == "StrictModel"
        assert "Invalid JSON response" in err.validation_errors

    def test_validation_failure_raises_llm_errors_class_with_attrs(self):
        with pytest.raises(llm_errors.ResponseParseError) as exc_info:
            ResponseParser.parse('{"count": "nope", "name": "x"}', StrictModel)
        err = exc_info.value
        assert err.expected_schema == "StrictModel"
        assert err.validation_errors  # Pydantic error details populated
        assert "count" in err.raw_content

    def test_except_clause_on_llm_errors_class_catches_parser_raise(self):
        """Regression for the original bug: callers catching the llm_errors
        class must actually catch what the parser raises."""
        caught = None
        try:
            ResponseParser.parse("definitely not json", StrictModel)
        except llm_errors.ResponseParseError as e:
            caught = e
        assert caught is not None
