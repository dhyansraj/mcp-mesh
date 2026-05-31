"""Unit tests for the version-aware capability resolver (RFC #1100, Phase 1).

These pin the resolver's structured-output mode decision to the EXACT behavior
that was previously inlined in each provider handler. They are decision-matrix
tests — they assert the resolved ``ModelCapabilities.structured_output`` value
for every vendor + request-shape combination, including date-pinned and
Bedrock-prefixed Anthropic model ids to lock the output_config regex gate.
"""

from __future__ import annotations

import pytest

from _mcp_mesh.engine.provider_handlers import capabilities as caps_mod
from _mcp_mesh.engine.provider_handlers.capabilities import (
    StructuredOutputMode,
    resolve_capabilities,
)


@pytest.fixture
def _anthropic_floor_met(monkeypatch):
    """Simulate a conforming anthropic install (>= 0.77) for OUTPUT_CONFIG
    mode-selection tests. CI has no anthropic SDK installed, so the resolver's
    real ``_sdk_at_least`` would return False and degrade to SYNTHETIC_TOOL —
    these tests assert mode SELECTION, not SDK detection (which is covered by
    dedicated gating tests)."""
    monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
    yield


class TestAnthropicResolver:
    """Reproduce ``ClaudeHandler.apply_structured_output`` selection."""

    def test_str_output_is_text(self):
        caps = resolve_capabilities(
            "anthropic",
            "anthropic/claude-sonnet-4-5",
            output_is_basemodel=False,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.TEXT

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-sonnet-4-5-20250101",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-1",
            "anthropic/claude-opus-4-5",
            "anthropic/claude-opus-4-7",
            # Bedrock-prefixed + date-pinned still match (re.search, not anchored).
            "anthropic.claude-sonnet-4-6-20260301-v1:0",
            # Dot separator variant.
            "anthropic/claude-sonnet-4.5",
        ],
    )
    def test_basemodel_native_buffered_supported_model_is_output_config(
        self, model, _anthropic_floor_met
    ):
        caps = resolve_capabilities(
            "anthropic",
            model,
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.OUTPUT_CONFIG

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-3-5-sonnet-20241022",
            "anthropic/claude-sonnet-4-0",
            "anthropic/claude-3-opus-20240229",
            "anthropic/claude-3-5-haiku-20241022",
            # Trailing-digit guard: opus-4-10 must NOT match the opus-4-1 pattern.
            "anthropic/claude-opus-4-10",
            None,
        ],
    )
    def test_basemodel_native_buffered_older_model_is_synthetic_tool(self, model):
        caps = resolve_capabilities(
            "anthropic",
            model,
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.SYNTHETIC_TOOL

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-3-5-haiku-20241022",
        ],
    )
    def test_basemodel_native_streaming_is_prose_hint(self, model):
        caps = resolve_capabilities(
            "anthropic",
            model,
            output_is_basemodel=True,
            has_native=True,
            streaming=True,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-3-5-haiku-20241022",
        ],
    )
    def test_basemodel_no_native_is_prose_hint(self, model):
        caps = resolve_capabilities(
            "anthropic",
            model,
            output_is_basemodel=True,
            has_native=False,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_output_config_sets_min_sdk_version(self, _anthropic_floor_met):
        caps = resolve_capabilities(
            "anthropic",
            "anthropic/claude-sonnet-4-5",
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.OUTPUT_CONFIG
        assert caps.min_sdk_version == "0.77"

    def test_output_config_gated_on_anthropic_floor(self, monkeypatch):
        """RFC #1100 Phase 2: a too-old anthropic SDK degrades OUTPUT_CONFIG to
        the next-best native mode (SYNTHETIC_TOOL). With the dependency floor
        now 0.77 this never trips in conforming installs; the gate keeps the
        resolver correct for constrained installs."""

        def _fake(dist, floor):
            if dist == "anthropic":
                return False  # simulate anthropic < 0.77
            return True

        monkeypatch.setattr(caps_mod, "_sdk_at_least", _fake)
        caps = resolve_capabilities(
            "anthropic",
            "anthropic/claude-sonnet-4-5",
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.SYNTHETIC_TOOL

    def test_output_config_selected_when_floor_met(self, monkeypatch):
        """Conforming install (anthropic >= 0.77) still selects OUTPUT_CONFIG."""

        monkeypatch.setattr(
            caps_mod, "_sdk_at_least", lambda dist, floor: True
        )
        caps = resolve_capabilities(
            "anthropic",
            "anthropic/claude-opus-4-1",
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.OUTPUT_CONFIG


class TestOpenAIResolver:
    """Reproduce ``OpenAIHandler.prepare_request`` selection (universal)."""

    def test_str_output_is_text(self):
        caps = resolve_capabilities(
            "openai", None, output_is_basemodel=False
        )
        assert caps.structured_output == StructuredOutputMode.TEXT

    @pytest.mark.parametrize("has_tools", [False, True])
    def test_basemodel_is_response_format_strict(self, has_tools):
        caps = resolve_capabilities(
            "openai", None, output_is_basemodel=True, has_tools=has_tools
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT


class TestGeminiResolver:
    """Reproduce ``GeminiHandler.prepare_request`` selection."""

    def test_str_output_is_text(self):
        caps = resolve_capabilities(
            "gemini", None, output_is_basemodel=False, has_tools=False
        )
        assert caps.structured_output == StructuredOutputMode.TEXT

    def test_basemodel_no_tools_is_response_format_strict(self):
        # model=None → no version known → unchanged RESPONSE_FORMAT_STRICT.
        caps = resolve_capabilities(
            "gemini", None, output_is_basemodel=True, has_tools=False
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT

    @pytest.mark.parametrize(
        "model",
        [
            "gemini/gemini-3-pro-preview",
            "gemini/gemini-3.0-flash",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.0-flash-lite",
            "gemini/gemini-1.5-pro",
        ],
    )
    def test_basemodel_no_tools_any_version_is_response_format_strict(self, model):
        """Gemini no-tools BaseModel always selects response_format/strict
        (flows to the adapter's response_schema field), independent of the
        model major version. The stricter ``response_json_schema`` variant is
        reserved (RFC #1100 follow-up) pending live-Gemini validation, so no
        resolver selects it yet."""
        caps = resolve_capabilities(
            "gemini", model, output_is_basemodel=True, has_tools=False
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT

    def test_basemodel_with_tools_is_prose_hint(self):
        caps = resolve_capabilities(
            "gemini", None, output_is_basemodel=True, has_tools=True
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_gemini_3_WITH_tools_is_prose_hint_unchanged(self, monkeypatch):
        """The Gemini-with-tools path is UNCHANGED — even Gemini 3.x with the
        new SDK stays on PROSE_HINT (the infinite-tool-loop gate). RFC #1100
        Phase 2 never touches the tools path."""
        monkeypatch.setattr(
            caps_mod, "_sdk_at_least", lambda dist, floor: True
        )
        caps = resolve_capabilities(
            "gemini",
            "gemini/gemini-3-pro-preview",
            output_is_basemodel=True,
            has_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT


class TestVersionHelpers:
    """Unit tests for the SDK-version detection / compare helpers."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0.77.0", (0, 77, 0)),
            ("1.22", (1, 22)),
            ("1.22.0rc1", (1, 22, 0)),
            ("0.77.0.dev3", (0, 77, 0)),
            ("1.22+local", (1, 22)),
            ("2", (2,)),
            ("", None),
            (None, None),
            ("not-a-version", None),
        ],
    )
    def test_parse_version(self, raw, expected):
        assert caps_mod._parse_version(raw) == expected

    def test_sdk_at_least_uninstalled_is_false(self, monkeypatch):
        monkeypatch.setattr(
            caps_mod, "_sdk_version", lambda dist: None
        )
        assert caps_mod._sdk_at_least("nonexistent-pkg", (1, 0)) is False

    def test_sdk_at_least_compares_tuples(self, monkeypatch):
        monkeypatch.setattr(
            caps_mod, "_sdk_version", lambda dist: "1.22.0"
        )
        assert caps_mod._sdk_at_least("google-genai", (1, 22)) is True
        assert caps_mod._sdk_at_least("google-genai", (1, 23)) is False
        assert caps_mod._sdk_at_least("google-genai", (1, 0)) is True


class TestGenericResolver:
    """Reproduce ``GenericHandler`` prose-only behavior."""

    def test_str_output_is_text(self):
        caps = resolve_capabilities(
            "cohere", None, output_is_basemodel=False
        )
        assert caps.structured_output == StructuredOutputMode.TEXT

    @pytest.mark.parametrize("vendor", ["cohere", "together", "unknown", "ollama"])
    def test_basemodel_is_prose_hint(self, vendor):
        caps = resolve_capabilities(
            vendor, None, output_is_basemodel=True
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT
