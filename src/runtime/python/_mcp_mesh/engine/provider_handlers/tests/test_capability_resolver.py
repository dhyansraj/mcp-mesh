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
    RECOVERY_NONE,
    RECOVERY_RESPONSE_FORMAT_RETRY,
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
            # #1331 refresh: Sonnet 5, Opus 4.6 / 4.8, Fable 5.
            "anthropic/claude-sonnet-5",
            "anthropic/claude-opus-4-6",
            "anthropic/claude-opus-4-8",
            "anthropic/claude-fable-5",
            # Bedrock-prefixed + date-pinned still match (re.search, not anchored).
            "anthropic.claude-sonnet-4-6-20260301-v1:0",
            "anthropic.claude-sonnet-5-20260101-v1:0",
            "anthropic.claude-opus-4-8-20260401-v1:0",
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
            "anthropic/claude-sonnet-4-5-20250101",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-1",
            "anthropic/claude-opus-4-5",
            "anthropic/claude-opus-4-7",
            "anthropic.claude-sonnet-4-6-20260301-v1:0",
            "anthropic/claude-sonnet-4.5",
        ],
    )
    def test_basemodel_native_streaming_supported_model_is_output_config(
        self, model, _anthropic_floor_met
    ):
        """RFC #1100: streaming + native + capable model → OUTPUT_CONFIG.
        ``client.messages.stream`` accepts ``output_config`` and the structured
        JSON streams as ``text_delta`` chunks."""
        caps = resolve_capabilities(
            "anthropic",
            model,
            output_is_basemodel=True,
            has_native=True,
            streaming=True,
        )
        assert caps.structured_output == StructuredOutputMode.OUTPUT_CONFIG
        assert caps.server_enforced is True
        assert caps.streaming_structured is True

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-3-5-sonnet-20241022",
            "anthropic/claude-sonnet-4-0",
            "anthropic/claude-3-opus-20240229",
            "anthropic/claude-3-5-haiku-20241022",
            "anthropic/claude-opus-4-10",
        ],
    )
    def test_basemodel_native_streaming_older_model_is_prose_hint(self, model):
        """Streaming + native but older (non-output_config-capable) model stays
        on PROSE_HINT — synthetic-tool injection doesn't chunk."""
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


class TestServerEnforcementMetadata:
    """Descriptor-metadata correctness for ``server_enforced``/``recovery``.

    These fields are currently descriptive-only (no control flow reads them),
    but must be accurate before a future phase makes them load-bearing.
    """

    def test_synthetic_tool_is_best_effort_with_retry_recovery(self):
        """SYNTHETIC_TOOL is NOT server-enforced: the model may decline the
        injected ``__mesh_format_response`` tool or emit invalid args, so it
        relies on corrective response_format retries (paths C/D)."""
        caps = resolve_capabilities(
            "anthropic",
            "anthropic/claude-3-5-sonnet-20241022",  # older model → SYNTHETIC_TOOL
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.SYNTHETIC_TOOL
        assert caps.server_enforced is False
        assert caps.recovery == RECOVERY_RESPONSE_FORMAT_RETRY

    def test_output_config_is_server_enforced_no_recovery(
        self, _anthropic_floor_met
    ):
        caps = resolve_capabilities(
            "anthropic",
            "anthropic/claude-sonnet-4-5",
            output_is_basemodel=True,
            has_native=True,
            streaming=False,
        )
        assert caps.structured_output == StructuredOutputMode.OUTPUT_CONFIG
        assert caps.server_enforced is True
        assert caps.recovery == RECOVERY_NONE

    def test_response_format_strict_is_server_enforced_no_recovery(self):
        caps = resolve_capabilities(
            "openai", None, output_is_basemodel=True
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT
        assert caps.server_enforced is True
        assert caps.recovery == RECOVERY_NONE


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
        only selected on the WITH-tools path (Gemini-3+), so the no-tools path
        is unchanged by the RFC #1100 follow-up default-on flip."""
        caps = resolve_capabilities(
            "gemini", model, output_is_basemodel=True, has_tools=False
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT

    def test_basemodel_with_tools_is_prose_hint(self):
        caps = resolve_capabilities(
            "gemini", None, output_is_basemodel=True, has_tools=True
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_gemini_3_WITH_tools_default_param_is_prose_hint(self, monkeypatch):
        """The resolver's ``gemini_native_structured_tools`` parameter defaults
        to False (resolver-level default). Callers pass the env-derived value;
        the handler reader is now default-ON (kill-switch). With the param
        left at its resolver default, Gemini 3.x + tools stays on PROSE_HINT —
        this pins the resolver signature default, not the runtime contract
        (covered by TestGeminiNativeStructuredToolsGate)."""
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


class TestGeminiNativeStructuredToolsGate:
    """Gemini-3 ``response_json_schema`` + tools path (RFC #1100 follow-up).
    Now DEFAULT ON at the runtime layer via a kill-switch
    (``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0`` disables). At the resolver
    layer the decision is driven by the ``gemini_native_structured_tools``
    parameter the handler passes in: True (default / kill-switch unset) +
    Gemini-3+ + google-genai >= 1.22 → RESPONSE_JSON_SCHEMA; False
    (kill-switch set) → PROSE_HINT."""

    @pytest.fixture
    def _genai_floor_met(self, monkeypatch):
        # CI may pin an older google-genai; assert SELECTION, not detection.
        monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
        yield

    def test_kill_switch_with_tools_is_prose_hint(self, _genai_floor_met):
        """Kill-switch (gemini_native_structured_tools=False): Gemini-3 + tools
        + new SDK reverts to PROSE_HINT — byte-identical to the pre-#1102
        default."""
        caps = resolve_capabilities(
            "gemini",
            "gemini/gemini-3-pro-preview",
            output_is_basemodel=True,
            has_tools=True,
            gemini_native_structured_tools=False,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_flag_on_gemini3_tools_sdk_ok_is_response_json_schema(
        self, _genai_floor_met
    ):
        caps = resolve_capabilities(
            "gemini",
            "gemini/gemini-3-pro-preview",
            output_is_basemodel=True,
            has_tools=True,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_JSON_SCHEMA
        assert caps.server_enforced is True
        assert caps.schema_with_tools is True
        assert caps.min_sdk_version == "1.22"

    @pytest.mark.parametrize(
        "model",
        [
            "gemini/gemini-3-pro-preview",
            "gemini/gemini-3.0-flash",
            "vertex_ai/gemini-3-flash",
        ],
    )
    def test_flag_on_various_gemini3_ids_is_response_json_schema(
        self, _genai_floor_met, model
    ):
        caps = resolve_capabilities(
            "gemini",
            model,
            output_is_basemodel=True,
            has_tools=True,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_JSON_SCHEMA

    @pytest.mark.parametrize(
        "model",
        [
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.0-flash-lite",
            "gemini/gemini-1.5-pro",
        ],
    )
    def test_flag_on_gemini2x_tools_is_prose_hint(self, _genai_floor_met, model):
        """Only Gemini-3+ unlocks the server-enforced path; 2.x / 1.x with
        tools stays on PROSE_HINT even with the flag enabled (default)."""
        caps = resolve_capabilities(
            "gemini",
            model,
            output_is_basemodel=True,
            has_tools=True,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_flag_on_unknown_model_is_prose_hint(self, _genai_floor_met):
        """model=None → major version unknown → conservative PROSE_HINT."""
        caps = resolve_capabilities(
            "gemini",
            None,
            output_is_basemodel=True,
            has_tools=True,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_flag_on_gemini3_but_sdk_too_old_is_prose_hint(self, monkeypatch):
        """genai < 1.22 → degrade to PROSE_HINT even on Gemini-3 + flag on."""
        monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: False)
        caps = resolve_capabilities(
            "gemini",
            "gemini/gemini-3-pro-preview",
            output_is_basemodel=True,
            has_tools=True,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.PROSE_HINT

    def test_flag_on_gemini3_NO_tools_is_response_format_strict(
        self, _genai_floor_met
    ):
        """No-tools path is unaffected by the gate — still RESPONSE_FORMAT_STRICT
        (the no-tools branch never reaches the gated check)."""
        caps = resolve_capabilities(
            "gemini",
            "gemini/gemini-3-pro-preview",
            output_is_basemodel=True,
            has_tools=False,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT

    def test_flag_on_str_output_is_text(self, _genai_floor_met):
        caps = resolve_capabilities(
            "gemini",
            "gemini/gemini-3-pro-preview",
            output_is_basemodel=False,
            has_tools=True,
            gemini_native_structured_tools=True,
        )
        assert caps.structured_output == StructuredOutputMode.TEXT


class TestGeminiMajorParser:
    """Unit tests for the Gemini major-version parser used by the gate."""

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("gemini/gemini-3-pro-preview", 3),
            ("gemini/gemini-3.0-flash", 3),
            ("vertex_ai/gemini-3-flash", 3),
            ("gemini/gemini-2.5-flash", 2),
            ("gemini/gemini-2.0-flash-lite", 2),
            ("gemini/gemini-1.5-pro", 1),
            ("gemini/gemini-10-future", 10),
            (None, None),
            ("", None),
            ("gpt-4o", None),
            ("claude-sonnet-4-5", None),
        ],
    )
    def test_gemini_major(self, model, expected):
        assert caps_mod._gemini_major(model) == expected


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
