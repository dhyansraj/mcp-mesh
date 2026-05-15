"""Unit tests for ClaudeHandler's native ``output_config`` branch.

The handler routes Sonnet 4.5+ / Opus 4.1+ buffered structured-output to a
``response_format`` payload (which the native Anthropic adapter translates to
``output_config.format`` on the wire) and stamps ``_mesh_output_config_mode``
so the agentic loop skips synthetic-fallback recovery. Older Claude models
(Haiku, Sonnet 3.x / 4.0, Opus 3.x) and the LiteLLM path keep their existing
synthetic-tool / HINT behavior.

Companion loop-side tests live in
``tests/unit/test_provider_agentic_loop_output_config.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import BaseModel

from _mcp_mesh.engine.provider_handlers.claude_handler import (
    SYNTHETIC_FORMAT_TOOL_NAME,
    ClaudeHandler,
)


class _Trip(BaseModel):
    destination: str
    days: int


def _trip_schema() -> dict:
    return _Trip.model_json_schema()


@pytest.fixture
def _native_on(monkeypatch):
    """Force ``ClaudeHandler.has_native()`` → True for the duration of the test.

    Patches the module-level lookup the handler uses, so we don't rely on the
    real anthropic SDK being importable in CI.
    """
    monkeypatch.setattr(ClaudeHandler, "has_native", lambda self: True)
    yield


@pytest.fixture
def _native_off(monkeypatch):
    """Force ``ClaudeHandler.has_native()`` → False — LiteLLM path."""
    monkeypatch.setattr(ClaudeHandler, "has_native", lambda self: False)
    yield


class TestApplyStructuredOutputOutputConfig:
    """Sonnet 4.5+ / Opus 4.1+ buffered + native SDK → ``output_config`` branch."""

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-sonnet-4.6",
        ],
    )
    def test_sonnet_buffered_native_sets_response_format_and_sentinel(
        self, _native_on, model
    ):
        """Sonnet 4.5+ + buffered + native must set ``response_format`` (the
        adapter translates to ``output_config.format``) AND stamp the
        ``_mesh_output_config_mode`` sentinel so the loop skips fallback.
        Synthetic-tool sentinels MUST NOT be present.
        """
        handler = ClaudeHandler()
        params: dict = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Plan a trip."},
            ]
        }
        result = handler.apply_structured_output(
            _trip_schema(), "Trip", params, model=model
        )

        # response_format is set with the LiteLLM-shape envelope; the adapter
        # translates it to output_config.format for allow-listed models.
        assert "response_format" in result
        rf = result["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "Trip"
        assert rf["json_schema"]["strict"] is True
        assert "destination" in rf["json_schema"]["schema"]["properties"]

        # Sentinel the agentic loop uses to short-circuit synthetic-fallback.
        assert result["_mesh_output_config_mode"] is True
        assert result["_mesh_output_config_output_type_name"] == "Trip"
        # Schema is captured for defense-in-depth parse check in the loop.
        assert result["_mesh_output_config_schema"] is not None

        # Synthetic-tool path MUST NOT fire — output_config supersedes it.
        assert "_mesh_synthetic_format_tool" not in result
        assert "_mesh_synthetic_format_tool_name" not in result
        # HINT mode is mutually exclusive.
        assert "_mesh_hint_mode" not in result

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-opus-4-1",
            "anthropic/claude-opus-4-5",
            "anthropic/claude-opus-4-7",
            "anthropic/claude-opus-4.7",
        ],
    )
    def test_opus_buffered_native_sets_response_format_and_sentinel(
        self, _native_on, model
    ):
        """Opus 4.1+ takes the same branch as Sonnet 4.5+."""
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            _trip_schema(), "Trip", params, model=model
        )

        assert "response_format" in result
        assert result["_mesh_output_config_mode"] is True
        assert "_mesh_synthetic_format_tool" not in result

    def test_output_config_does_not_inject_system_addendum(self, _native_on):
        """``output_config`` mode must NOT append the synthetic "must call this
        tool" instruction to the system message — the API enforces the schema
        directly, there is no synthetic tool to call.
        """
        handler = ClaudeHandler()
        original = "You are a travel planner."
        params: dict = {
            "messages": [
                {"role": "system", "content": original},
                {"role": "user", "content": "Plan a trip."},
            ]
        }
        handler.apply_structured_output(
            _trip_schema(),
            "Trip",
            params,
            model="anthropic/claude-sonnet-4-6",
        )

        system_content = params["messages"][0]["content"]
        # System message is left alone — no synthetic-tool addendum, no HINT
        # OUTPUT FORMAT block.
        assert system_content == original
        assert "__mesh_format_response" not in system_content
        assert "OUTPUT FORMAT" not in system_content

    def test_output_config_clears_stale_sentinels(self, _native_on):
        """Defense-in-depth: any leftover HINT or synthetic-tool sentinels
        from a prior code path MUST be cleared so the loop's mode detection
        is unambiguous.
        """
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}],
            # Pre-existing sentinels (simulating a buggy re-entry path).
            "_mesh_hint_mode": True,
            "_mesh_hint_schema": {"some": "schema"},
            "_mesh_synthetic_format_tool_name": SYNTHETIC_FORMAT_TOOL_NAME,
            "_mesh_synthetic_format_tool": {"some": "tool"},
        }
        result = handler.apply_structured_output(
            _trip_schema(), "Trip", params, model="anthropic/claude-sonnet-4-6"
        )

        # Cleared.
        assert "_mesh_hint_mode" not in result
        assert "_mesh_hint_schema" not in result
        assert "_mesh_synthetic_format_tool_name" not in result
        assert "_mesh_synthetic_format_tool" not in result
        # output_config sentinels set.
        assert result["_mesh_output_config_mode"] is True


class TestApplyNativeOutputConfigStrictification:
    """Anthropic's ``output_config`` endpoint requires
    ``additionalProperties: false`` on every object-typed schema node. The
    handler must run the schema through ``make_schema_strict`` (with
    ``add_all_required=False`` to match Anthropic's looser ``required``
    semantics) before stamping ``response_format``."""

    def test_apply_native_output_config_strict_ifies_schema(self, _native_on):
        """A schema with nested objects WITHOUT ``additionalProperties`` must
        come out with ``additionalProperties: false`` at every object level
        in the response_format payload (and in the captured sentinel schema).
        """
        handler = ClaudeHandler()

        # Hand-built schema with a nested object — none of the object nodes
        # declare ``additionalProperties``.
        schema = {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "itinerary": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "activity": {"type": "string"},
                    },
                },
            },
            "required": ["destination"],
        }
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            schema, "Trip", params, model="anthropic/claude-sonnet-4-6"
        )

        rf_schema = result["response_format"]["json_schema"]["schema"]
        # Top-level object node.
        assert rf_schema["additionalProperties"] is False
        # Nested object node.
        nested = rf_schema["properties"]["itinerary"]
        assert nested["additionalProperties"] is False

        # The captured sentinel schema must match the wire-level shape.
        sentinel_schema = result["_mesh_output_config_schema"]
        assert sentinel_schema["additionalProperties"] is False
        assert (
            sentinel_schema["properties"]["itinerary"]["additionalProperties"]
            is False
        )

    def test_apply_native_output_config_preserves_required_list(self, _native_on):
        """``add_all_required=False`` semantics — the existing ``required``
        list passes through unchanged; we do NOT add every property to
        ``required`` (that's the OpenAI/Gemini strict semantics, not
        Anthropic's)."""
        handler = ClaudeHandler()

        schema = {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "days": {"type": "integer"},
                "notes": {"type": "string"},
            },
            # Only one of three properties required.
            "required": ["destination"],
        }
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            schema, "Trip", params, model="anthropic/claude-sonnet-4-6"
        )

        rf_schema = result["response_format"]["json_schema"]["schema"]
        # ``required`` preserved as-is — NOT expanded to all property keys.
        assert rf_schema["required"] == ["destination"]

    def test_apply_native_output_config_captured_schema_matches_wire(
        self, _native_on
    ):
        """Regression guard for PR #1013 review WARNING 3.

        The captured ``_mesh_output_config_schema`` must match the on-wire
        schema. The adapter strips ``maxItems`` / ``minItems`` before sending
        (Anthropic issue #19444); if the handler stamps the pre-filter schema
        instead, the loop's defense-in-depth parse check (which uses the
        sentinel) WARNs misleadingly on responses that violate constraints
        Anthropic never enforced.
        """
        handler = ClaudeHandler()
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "minItems": 1,
                },
            },
            "required": ["tags"],
        }
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            schema, "Tagged", params, model="anthropic/claude-sonnet-4-6"
        )

        # The captured sentinel schema must NOT carry maxItems / minItems —
        # those are stripped from the wire payload too.
        sentinel_schema = result["_mesh_output_config_schema"]
        tags_node = sentinel_schema["properties"]["tags"]
        assert "maxItems" not in tags_node
        assert "minItems" not in tags_node

        # And the response_format payload (what literally goes on the wire)
        # must agree.
        rf_tags = result["response_format"]["json_schema"]["schema"][
            "properties"
        ]["tags"]
        assert "maxItems" not in rf_tags
        assert "minItems" not in rf_tags


class TestApplyStructuredOutputHaikuFallsThroughToSynthetic:
    """Haiku / older Claude models route to the synthetic-tool path even on
    the native SDK — they don't accept ``output_config.format``."""

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-3-5-haiku-20241022",
            "anthropic/claude-3-5-sonnet-20241022",  # Sonnet 3.5 (pre-4.5)
            "anthropic/claude-3-opus-20240229",  # Opus 3 (pre-4.1)
        ],
    )
    def test_legacy_models_route_to_synthetic_tool_path(self, _native_on, model):
        """Older Anthropic models keep the existing synthetic-tool injection.
        ``response_format`` MUST NOT be set; ``_mesh_output_config_mode`` MUST
        NOT be stamped.
        """
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            _trip_schema(), "Trip", params, model=model
        )

        # Synthetic-tool sentinels present.
        assert (
            result["_mesh_synthetic_format_tool_name"]
            == SYNTHETIC_FORMAT_TOOL_NAME
        )
        assert "_mesh_synthetic_format_tool" in result
        # output_config mode NOT set.
        assert "_mesh_output_config_mode" not in result
        assert "response_format" not in result


class TestApplyStructuredOutputStreamingRoutingPreserved:
    """Phase C: streaming + structured output prefers HINT mode regardless of
    the new output_config branch. The model gate is only consulted when
    ``streaming=False``."""

    @pytest.mark.parametrize(
        "model",
        ["anthropic/claude-sonnet-4-6", "anthropic/claude-opus-4-7"],
    )
    def test_streaming_sonnet_4_6_still_routes_to_hint(self, _native_on, model):
        """Streaming MUST take the HINT path even on output_config-capable
        models — the API's output_config is buffered-only in this design."""
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            _trip_schema(), "Trip", params, streaming=True, model=model
        )

        # HINT sentinels stamped.
        assert result["_mesh_hint_mode"] is True
        # output_config sentinels MUST NOT be present.
        assert "_mesh_output_config_mode" not in result
        # response_format must NOT leak through (issue #820 silent hang).
        assert "response_format" not in result

    def test_buffered_haiku_without_native_falls_through_to_hint(
        self, _native_off
    ):
        """When the native SDK is unavailable, the output_config branch is
        not eligible — fall through to the existing HINT-mode path. (Haiku
        on LiteLLM path: HINT mode.)
        """
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            _trip_schema(),
            "Trip",
            params,
            model="anthropic/claude-sonnet-4-6",
        )

        # HINT sentinels stamped.
        assert result["_mesh_hint_mode"] is True
        # output_config + synthetic sentinels MUST NOT be present.
        assert "_mesh_output_config_mode" not in result
        assert "_mesh_synthetic_format_tool" not in result

    def test_buffered_sonnet_4_6_without_native_falls_through_to_hint(
        self, _native_off
    ):
        """``has_native()`` False — even Sonnet 4.6 falls through to HINT mode."""
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        result = handler.apply_structured_output(
            _trip_schema(),
            "Trip",
            params,
            model="anthropic/claude-sonnet-4-6",
        )

        assert result["_mesh_hint_mode"] is True
        assert "_mesh_output_config_mode" not in result

    def test_model_unset_falls_through_to_synthetic_tool_path(self, _native_on):
        """When ``model`` is None (older callers / defensive default), the
        output_config branch cannot model-gate — fall through to the
        synthetic-tool path (the existing behavior for the native + buffered
        combo)."""
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "S"}]
        }
        # No model kwarg.
        result = handler.apply_structured_output(_trip_schema(), "Trip", params)

        assert (
            result["_mesh_synthetic_format_tool_name"]
            == SYNTHETIC_FORMAT_TOOL_NAME
        )
        assert "_mesh_output_config_mode" not in result
