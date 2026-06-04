"""
Unit tests for ResponseParser single-value-as-array leniency (issue #1142).

Under output_mode=hint the provider embeds the response schema in the prompt
but does not enforce it natively, so the LLM can emit a scalar where the schema
declares a list (e.g. "insights": "x" instead of ["x"]). The parser coerces that
single-value-as-array drift before Pydantic validation. This is a no-op for
well-shaped (strict) output where the value is already a list.
"""

from typing import List, Optional

from pydantic import BaseModel

from _mcp_mesh.engine.response_parser import ResponseParser


class Analysis(BaseModel):
    summary: str
    insights: List[str]


class OptionalListModel(BaseModel):
    tags: Optional[List[str]] = None


class TestResponseParserScalarList:
    def test_scalar_coerced_to_single_element_list(self):
        """A bare string for a List[str] field becomes a single-element list."""
        data = {"summary": "ok", "insights": "only-one"}
        parsed = ResponseParser.parse(data, Analysis)
        assert isinstance(parsed, Analysis)
        assert parsed.summary == "ok"
        assert parsed.insights == ["only-one"]

    def test_scalar_coerced_from_json_string(self):
        """Same drift arriving as a raw JSON string is coerced too."""
        content = '{"summary": "ok", "insights": "only-one"}'
        parsed = ResponseParser.parse(content, Analysis)
        assert parsed.insights == ["only-one"]

    def test_well_shaped_array_unchanged(self):
        """A correct array passes through untouched (no-op for strict output)."""
        data = {"summary": "ok", "insights": ["a", "b"]}
        parsed = ResponseParser.parse(data, Analysis)
        assert parsed.insights == ["a", "b"]

    def test_non_list_scalar_field_unaffected(self):
        """Scalar fields keep their scalar value; only list fields are coerced."""
        data = {"summary": "ok", "insights": ["a"]}
        parsed = ResponseParser.parse(data, Analysis)
        assert parsed.summary == "ok"

    def test_optional_list_scalar_coerced(self):
        """Optional[List[str]] also coerces a scalar to a single-element list."""
        data = {"tags": "urgent"}
        parsed = ResponseParser.parse(data, OptionalListModel)
        assert parsed.tags == ["urgent"]

    def test_optional_list_none_unchanged(self):
        """A None value for an optional list field is left as None."""
        data = {"tags": None}
        parsed = ResponseParser.parse(data, OptionalListModel)
        assert parsed.tags is None
