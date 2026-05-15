"""Adapter-level tests for the native ``output_config.format`` branch
(Sonnet 4.5+ / Opus 4.1+).

When ``response_format`` is set and the model is in the native allow-list
and ``stream=False`` and the handler hasn't already injected a synthetic
tool, the adapter translates ``response_format`` into Anthropic's
first-class ``output_config.format`` primitive instead of synthetic-tool
injection.

Older models (Haiku, Sonnet 3.x / 4.0, Opus 3.x) fall through to the
existing synthetic-tool path — that fallback path is covered by
``test_anthropic_native_response_format.py``.

Real network calls are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "anthropic", reason="native Anthropic adapter requires the anthropic SDK"
)

from _mcp_mesh.engine._structured_output_helpers import (
    SYNTHETIC_FORMAT_TOOL_NAME,
    schema_to_synthetic_tool,
)
from _mcp_mesh.engine.native_clients import anthropic_native


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_anthropic_message(text: str = '{"answer": "ok"}'):
    """Minimal anthropic.types.Message-like response.

    Default text payload mirrors the native output_config wire response:
    a single TextBlock whose .text IS the JSON string answer.
    """
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    return SimpleNamespace(content=[block], usage=usage, model="claude-test")


def _patched_async_anthropic(api_response):
    """Patch anthropic.AsyncAnthropic so .messages.create returns api_response.

    Returns ``(cls_mock, create_mock)`` so tests can both substitute the
    SDK class and inspect the kwargs the adapter forwards.
    """
    instance = MagicMock()
    create_mock = AsyncMock(return_value=api_response)
    instance.messages = MagicMock()
    instance.messages.create = create_mock
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, create_mock


_SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "TestResponse",
        "schema": _SIMPLE_SCHEMA,
        "strict": True,
    },
}


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """Reset the per-key WARN dedupe set so tests in this module don't
    observe state leaked from earlier tests in the same process."""
    anthropic_native._reset_unsupported_kwargs_dedupe()
    yield
    anthropic_native._reset_unsupported_kwargs_dedupe()


# ---------------------------------------------------------------------------
# _supports_native_output_format — model gating helper
# ---------------------------------------------------------------------------


class TestSupportsNativeOutputFormat:
    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-sonnet-4-5-20250929",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-sonnet-4-6-20260301",
            "anthropic/claude-opus-4-1",
            "anthropic/claude-opus-4.1",
            "anthropic/claude-opus-4-5",
            "anthropic/claude-opus-4-7",
            "anthropic/claude-opus-4.7",
            # Bedrock prefix + substring match.
            "bedrock/anthropic.claude-sonnet-4-6-20260301-v1:0",
            "bedrock/anthropic.claude-opus-4-7-20260401-v1:0",
            # Databricks prefix.
            "databricks/anthropic.claude-sonnet-4-6",
            # Case-insensitive (defensive).
            "ANTHROPIC/CLAUDE-SONNET-4-6",
        ],
    )
    def test_allow_list_positive(self, model):
        assert anthropic_native._supports_native_output_format(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            # Haiku — intentionally excluded per LiteLLM design.
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-haiku-4-5-20250929",
            "bedrock/anthropic.claude-haiku-4-5-20250929-v1:0",
            # Pre-4.5 Sonnet variants — synthetic-tool path.
            "anthropic/claude-3-5-sonnet",
            "anthropic/claude-3-5-sonnet-20241022",
            "anthropic/claude-3-sonnet-20240229",
            "anthropic/claude-sonnet-4-0",
            # Pre-4.1 Opus.
            "anthropic/claude-3-opus-20240229",
            # Empty / None — defensive.
            "",
        ],
    )
    def test_allow_list_negative(self, model):
        assert anthropic_native._supports_native_output_format(model) is False

    def test_none_input(self):
        assert anthropic_native._supports_native_output_format(None) is False


# ---------------------------------------------------------------------------
# _filter_anthropic_output_schema — maxItems/minItems stripper
# ---------------------------------------------------------------------------


class TestFilterAnthropicOutputSchema:
    def test_strips_top_level_max_min_items(self):
        schema = {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 10,
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        assert "minItems" not in out
        assert "maxItems" not in out
        assert out["type"] == "array"
        assert out["items"] == {"type": "string"}

    def test_strips_nested_in_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                },
                "name": {"type": "string"},
            },
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        tags = out["properties"]["tags"]
        assert "minItems" not in tags
        assert "maxItems" not in tags
        assert tags["type"] == "array"
        assert tags["items"] == {"type": "string"}
        # Sibling property unaffected.
        assert out["properties"]["name"] == {"type": "string"}

    def test_strips_in_items_nested_array(self):
        # Array-of-arrays — inner array has maxItems.
        schema = {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        assert "maxItems" not in out["items"]
        assert out["items"]["items"] == {"type": "string"}

    def test_strips_in_defs(self):
        schema = {
            "$defs": {
                "Tag": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            "type": "object",
            "properties": {"tag": {"$ref": "#/$defs/Tag"}},
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        assert "minItems" not in out["$defs"]["Tag"]
        assert out["$defs"]["Tag"]["items"] == {"type": "string"}

    def test_strips_in_anyof(self):
        schema = {
            "anyOf": [
                {"type": "string"},
                {
                    "type": "array",
                    "items": {"type": "integer"},
                    "maxItems": 4,
                },
            ]
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        assert "maxItems" not in out["anyOf"][1]
        assert out["anyOf"][0] == {"type": "string"}

    def test_strips_in_oneof_and_allof(self):
        schema = {
            "oneOf": [{"type": "array", "minItems": 1}],
            "allOf": [{"type": "array", "maxItems": 2}],
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        assert "minItems" not in out["oneOf"][0]
        assert "maxItems" not in out["allOf"][0]

    def test_idempotent(self):
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                }
            },
        }
        once = anthropic_native._filter_anthropic_output_schema(schema)
        twice = anthropic_native._filter_anthropic_output_schema(once)
        assert once == twice

    def test_handles_non_dict_input(self):
        assert anthropic_native._filter_anthropic_output_schema("scalar") == "scalar"
        assert anthropic_native._filter_anthropic_output_schema(42) == 42
        assert anthropic_native._filter_anthropic_output_schema(None) is None

    def test_preserves_other_fields(self):
        schema = {
            "type": "object",
            "description": "A tagged thing.",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {"name": {"type": "string", "minLength": 1}},
        }
        out = anthropic_native._filter_anthropic_output_schema(schema)
        assert out["description"] == "A tagged thing."
        assert out["additionalProperties"] is False
        assert out["required"] == ["name"]
        assert out["properties"]["name"]["minLength"] == 1


# ---------------------------------------------------------------------------
# Native output_config branch routing
# ---------------------------------------------------------------------------


class TestNativeOutputConfigRouting:
    @pytest.mark.asyncio
    async def test_sonnet_4_6_emits_output_config(self):
        """Sonnet 4.6 + response_format + no synthetic + stream=False →
        ``output_config.format`` is emitted; synthetic-tool path NOT taken."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-6",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        # response_format MUST be popped (SDK would reject it).
        assert "response_format" not in kwargs
        # output_config emitted with the LiteLLM-shape schema unwrapped.
        assert "output_config" in kwargs
        assert kwargs["output_config"] == {
            "format": {"type": "json_schema", "schema": _SIMPLE_SCHEMA}
        }
        # Synthetic-tool path NOT taken.
        assert "tools" not in kwargs or not kwargs.get("tools")
        # No system-instruction addendum.
        assert "system" not in kwargs

    @pytest.mark.asyncio
    async def test_opus_4_7_emits_output_config(self):
        """Opus 4.7 + response_format → output_config (same routing as Sonnet)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-opus-4-7",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "response_format" not in kwargs
        assert "output_config" in kwargs
        assert kwargs["output_config"]["format"]["type"] == "json_schema"

    @pytest.mark.asyncio
    async def test_haiku_4_5_falls_through_to_synthetic_tool(self):
        """Haiku 4.5 + response_format → synthetic-tool path (no output_config)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-haiku-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "response_format" not in kwargs
        # NOT routed through native output_config.
        assert "output_config" not in kwargs
        # Synthetic-tool path engaged.
        tools = kwargs.get("tools") or []
        assert any(t.get("name") == SYNTHETIC_FORMAT_TOOL_NAME for t in tools)

    @pytest.mark.asyncio
    async def test_handler_already_injected_short_circuits(self):
        """When the handler has already injected the synthetic tool, the
        adapter MUST NOT emit ``output_config`` — even on Sonnet 4.6."""
        handler_injected_tool = schema_to_synthetic_tool(_SIMPLE_SCHEMA)

        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [handler_injected_tool],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-6",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "response_format" not in kwargs
        # Handler-injected wins; no output_config downgrade.
        assert "output_config" not in kwargs
        # Synthetic still present (handler-injected, not adapter-duplicated).
        tools = kwargs.get("tools") or []
        synthetic_count = sum(
            1 for t in tools if t.get("name") == SYNTHETIC_FORMAT_TOOL_NAME
        )
        assert synthetic_count == 1

    @pytest.mark.asyncio
    async def test_stream_true_falls_through_to_synthetic_tool(self):
        """Defensive: ``stream=True`` MUST fall through to synthetic-tool
        path. Streaming output_config requires separate wire-up (deferred)."""
        # Direct call to _build_create_kwargs to inject stream=True without
        # actually opening a streaming context.
        create_kwargs = anthropic_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi."}],
                "response_format": _RESPONSE_FORMAT,
            },
            model="anthropic/claude-sonnet-4-6",
            stream=True,
        )
        # No native output_config — streaming branch defers.
        assert "output_config" not in create_kwargs
        # Synthetic-tool path engaged instead.
        tools = create_kwargs.get("tools") or []
        assert any(t.get("name") == SYNTHETIC_FORMAT_TOOL_NAME for t in tools)

    @pytest.mark.asyncio
    async def test_no_response_format_no_output_config(self):
        """Without ``response_format``, no output_config is emitted even on
        Sonnet 4.6 (sanity)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-6",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "output_config" not in kwargs

    @pytest.mark.asyncio
    async def test_bedrock_sonnet_4_6_emits_output_config(self):
        """Bedrock model id (``anthropic.`` prefix + date suffix) is matched
        by the substring allow-list."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropicBedrock", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="bedrock/anthropic.claude-sonnet-4-6-20260301-v1:0",
            )

        kwargs = create_mock.call_args.kwargs
        assert "output_config" in kwargs

    @pytest.mark.asyncio
    async def test_real_tool_preserved_alongside_output_config(self):
        """``response_format`` + Sonnet 4.6 + a real tool → ``output_config``
        set AND the real tool preserved in ``tools[]``."""
        real_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up weather.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [real_tool],
                    "response_format": _RESPONSE_FORMAT,
                },
                model="anthropic/claude-sonnet-4-6",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "output_config" in kwargs
        tool_names = {t.get("name") for t in kwargs.get("tools") or []}
        # Real tool preserved; synthetic NOT injected (native path).
        assert "get_weather" in tool_names
        assert SYNTHETIC_FORMAT_TOOL_NAME not in tool_names

    @pytest.mark.asyncio
    async def test_schema_filter_applied_in_native_branch(self):
        """A schema carrying ``maxItems`` / ``minItems`` MUST be stripped
        before being placed on ``output_config.format.schema``."""
        schema_with_limits = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                }
            },
            "required": ["tags"],
            "additionalProperties": False,
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "Tagged",
                "schema": schema_with_limits,
                "strict": True,
            },
        }
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": response_format,
                },
                model="anthropic/claude-sonnet-4-6",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        wire_schema = kwargs["output_config"]["format"]["schema"]
        tags_schema = wire_schema["properties"]["tags"]
        assert "minItems" not in tags_schema
        assert "maxItems" not in tags_schema
        # Other fields preserved.
        assert tags_schema["type"] == "array"
        assert tags_schema["items"] == {"type": "string"}
        # Original caller dict not mutated (caller may reuse it).
        assert (
            schema_with_limits["properties"]["tags"]["minItems"] == 1
        ), "Original schema was mutated; filter must be non-destructive."

    @pytest.mark.asyncio
    async def test_output_config_does_not_warn(self, caplog):
        """``response_format`` translated to ``output_config`` MUST NOT
        trigger the unsupported-kwarg WARN (output_config is now in
        ``_ANTHROPIC_PASSTHROUGH_KWARGS``)."""
        cls_mock, create_mock = _patched_async_anthropic(_make_anthropic_message())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "response_format": _RESPONSE_FORMAT,
                    },
                    model="anthropic/claude-sonnet-4-6",
                    api_key="sk-test",
                )

        warns = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert all("output_config" not in m for m in warns), (
            f"output_config triggered WARN; got: {warns}"
        )
