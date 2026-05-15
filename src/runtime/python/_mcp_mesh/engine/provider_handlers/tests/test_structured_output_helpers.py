"""Unit tests for ``_mcp_mesh.engine._structured_output_helpers``.

The helpers module is the single source of truth for the synthetic-tool
structured-output pattern wire shape. Two injection paths consume it:
``ClaudeHandler._apply_native_synthetic_format`` and adapter-side
``anthropic_native._build_create_kwargs``. These tests pin the wire-shape
identity so the two paths can never silently drift.

All helpers are pure functions; no fixtures needed.
"""

from __future__ import annotations

import pytest

from _mcp_mesh.engine._structured_output_helpers import (
    SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION,
    SYNTHETIC_FORMAT_TOOL_DESCRIPTION,
    SYNTHETIC_FORMAT_TOOL_NAME,
    append_synthetic_system_instruction,
    build_synthetic_tool_choice,
    is_synthetic_tool_in_list,
    schema_to_synthetic_tool,
)


# ---------------------------------------------------------------------------
# schema_to_synthetic_tool
# ---------------------------------------------------------------------------


class TestSchemaToSyntheticTool:
    def test_default_name_and_description(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        tool = schema_to_synthetic_tool(schema)

        assert tool["type"] == "function"
        assert tool["function"]["name"] == SYNTHETIC_FORMAT_TOOL_NAME
        assert tool["function"]["description"] == SYNTHETIC_FORMAT_TOOL_DESCRIPTION

    def test_custom_name_override(self):
        schema = {"type": "object", "properties": {}}
        tool = schema_to_synthetic_tool(schema, tool_name="my_custom_tool")

        assert tool["function"]["name"] == "my_custom_tool"

    def test_schema_placed_verbatim_under_parameters(self):
        """The schema dict MUST appear verbatim under function.parameters —
        downstream ``_convert_tools`` translators rely on the OpenAI shape."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
            "additionalProperties": False,
        }
        tool = schema_to_synthetic_tool(schema)

        # Identity check: same object reference under parameters.
        assert tool["function"]["parameters"] is schema


# ---------------------------------------------------------------------------
# build_synthetic_tool_choice
# ---------------------------------------------------------------------------


class TestBuildSyntheticToolChoice:
    def test_no_real_tools_forces_synthetic(self):
        """When no real tools are in play, force the synthetic tool — single
        deterministic round-trip."""
        choice = build_synthetic_tool_choice(real_tools_present=False)

        assert choice == {
            "type": "function",
            "function": {"name": SYNTHETIC_FORMAT_TOOL_NAME},
        }

    def test_real_tools_present_uses_auto(self):
        """When real tools coexist, ``"auto"`` lets the model pick between
        them and the synthetic — matches TS Vercel-AI-SDK / Java Spring-AI."""
        choice = build_synthetic_tool_choice(real_tools_present=True)

        assert choice == "auto"

    def test_custom_tool_name_in_forced_choice(self):
        choice = build_synthetic_tool_choice(
            real_tools_present=False, tool_name="alt_tool"
        )

        assert choice == {"type": "function", "function": {"name": "alt_tool"}}


# ---------------------------------------------------------------------------
# append_synthetic_system_instruction
# ---------------------------------------------------------------------------


class TestAppendSyntheticSystemInstruction:
    def test_none_input_returns_stripped_instruction(self):
        out = append_synthetic_system_instruction(None)

        # Leading whitespace stripped (no preceding system content to glue to).
        assert out == SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n")
        assert SYNTHETIC_FORMAT_TOOL_NAME in out

    def test_empty_string_returns_stripped_instruction(self):
        out = append_synthetic_system_instruction("")

        assert out == SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n")

    def test_non_empty_string_appends_instruction(self):
        out = append_synthetic_system_instruction("You are helpful.")

        assert out.startswith("You are helpful.")
        assert out.endswith(SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION)
        # The full instruction (with leading whitespace) is appended verbatim.
        assert out == "You are helpful." + SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION


# ---------------------------------------------------------------------------
# is_synthetic_tool_in_list
# ---------------------------------------------------------------------------


class TestIsSyntheticToolInList:
    def test_positive_openai_shape(self):
        tools = [
            schema_to_synthetic_tool({"type": "object", "properties": {}}),
        ]

        assert is_synthetic_tool_in_list(tools) is True

    def test_positive_anthropic_shape(self):
        """Adapter-side coordination MUST also recognize the
        already-translated Anthropic shape (``name`` + ``input_schema``)."""
        tools = [
            {
                "name": SYNTHETIC_FORMAT_TOOL_NAME,
                "description": "x",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]

        assert is_synthetic_tool_in_list(tools) is True

    def test_negative_other_tool_name(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "parameters": {"type": "object"},
                },
            }
        ]

        assert is_synthetic_tool_in_list(tools) is False

    @pytest.mark.parametrize("tools", [None, []])
    def test_none_and_empty(self, tools):
        assert is_synthetic_tool_in_list(tools) is False

    def test_skips_non_dict_entries(self):
        """Tolerate malformed lists: non-dict entries are skipped, not raised."""
        tools = [
            "not-a-dict",
            None,
            42,
            {
                "type": "function",
                "function": {"name": SYNTHETIC_FORMAT_TOOL_NAME},
            },
        ]

        assert is_synthetic_tool_in_list(tools) is True

    def test_mixed_real_and_synthetic(self):
        """Real tools alongside the synthetic still recognize the synthetic."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "parameters": {"type": "object"},
                },
            },
            schema_to_synthetic_tool({"type": "object", "properties": {}}),
        ]

        assert is_synthetic_tool_in_list(tools) is True
