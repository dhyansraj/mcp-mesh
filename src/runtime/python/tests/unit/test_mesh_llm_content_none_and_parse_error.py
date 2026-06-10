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

import pytest
from _mcp_mesh.engine import llm_errors, response_parser
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
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
