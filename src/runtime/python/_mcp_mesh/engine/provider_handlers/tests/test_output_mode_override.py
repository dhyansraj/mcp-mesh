"""Unit tests for the consumer-supplied ``output_mode`` override (finding #6).

Covers the provider-side ``apply_structured_output`` honoring of a valid
``output_mode`` for the OpenAI and Gemini handlers, plus the no-regression
default (override unset → per-vendor auto-selection unchanged) and the
invalid-value behavior (ignore + auto + warning).

Mocked at the handler level — no real LLM calls.
"""

from __future__ import annotations

import logging
import os

import pytest

from _mcp_mesh.engine.provider_handlers import capabilities as caps_mod
from _mcp_mesh.engine.provider_handlers.claude_handler import (
    SYNTHETIC_FORMAT_TOOL_NAME,
    ClaudeHandler,
)
from _mcp_mesh.engine.provider_handlers.gemini_handler import GeminiHandler
from _mcp_mesh.engine.provider_handlers.openai_handler import OpenAIHandler

_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}

_GATE = "MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS"
_MARKER = "_mesh_gemini_response_json_schema"

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "noop",
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


@pytest.fixture(autouse=True)
def _clean_gate_env():
    """Ensure the Gemini gated-path flag never leaks across these tests."""
    original = os.environ.pop(_GATE, None)
    yield
    if original is not None:
        os.environ[_GATE] = original
    else:
        os.environ.pop(_GATE, None)


# ---------------------------------------------------------------------------
# OpenAI handler
# ---------------------------------------------------------------------------


class TestOpenAIOutputModeOverride:
    def test_default_none_uses_native_response_format(self):
        """No override → native response_format strict (no regression)."""
        handler = OpenAIHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(_SCHEMA, "Plan", params)
        assert out["response_format"]["type"] == "json_schema"
        assert out["response_format"]["json_schema"]["strict"] is True
        assert "_mesh_hint_mode" not in out

    def test_override_strict_uses_native_response_format(self):
        """output_mode='strict' → native response_format (same as auto)."""
        handler = OpenAIHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, output_mode="strict"
        )
        assert out["response_format"]["type"] == "json_schema"
        assert "_mesh_hint_mode" not in out

    def test_override_hint_takes_hint_branch(self):
        """output_mode='hint' → prose HINT even though OpenAI auto-selects
        native response_format. response_format is dropped; the _mesh_hint_*
        sentinels are stamped and the schema is injected into the prompt."""
        handler = OpenAIHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, output_mode="hint"
        )
        assert out["_mesh_hint_mode"] is True
        assert "response_format" not in out
        # Schema injected into the system message.
        assert "OUTPUT FORMAT" in out["messages"][0]["content"]

    def test_override_text_disables_schema_enforcement(self):
        """output_mode='text' → no response_format, no HINT sentinels."""
        handler = OpenAIHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "response_format": {"type": "json_schema", "json_schema": {}},
        }
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, output_mode="text"
        )
        assert "response_format" not in out
        assert "_mesh_hint_mode" not in out

    def test_invalid_override_ignored_falls_back_to_auto_with_warning(self, caplog):
        """Invalid override → ignored (warning) + auto (native response_format)."""
        handler = OpenAIHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        with caplog.at_level(logging.WARNING):
            out = handler.apply_structured_output(
                _SCHEMA, "Plan", params, output_mode="bogus"
            )
        assert out["response_format"]["type"] == "json_schema"
        assert "_mesh_hint_mode" not in out
        assert any("invalid output_mode" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Gemini handler
# ---------------------------------------------------------------------------


class TestGeminiOutputModeOverride:
    def test_default_none_gemini2x_auto_hint(self):
        """No override + Gemini-2.x + tools → auto HINT (no regression)."""
        handler = GeminiHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "tools": _TOOLS,
        }
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, model="gemini/gemini-2.5-flash"
        )
        assert out["_mesh_hint_mode"] is True
        assert _MARKER not in out

    def test_override_hint_forces_hint_on_gemini3(self, monkeypatch):
        """output_mode='hint' forces HINT even when Gemini-3 + tools + modern
        SDK would auto-select the server-enforced response_json_schema."""
        monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
        handler = GeminiHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "tools": _TOOLS,
        }
        out = handler.apply_structured_output(
            _SCHEMA,
            "Plan",
            params,
            model="gemini/gemini-3-pro-preview",
            output_mode="hint",
        )
        assert out["_mesh_hint_mode"] is True
        assert _MARKER not in out
        assert "response_format" not in out

    def test_override_strict_uses_response_json_schema_on_gemini3(self, monkeypatch):
        """output_mode='strict' → server-enforced response_json_schema when the
        model/SDK qualify (Gemini-3+, modern SDK)."""
        monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
        handler = GeminiHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "tools": _TOOLS,
        }
        out = handler.apply_structured_output(
            _SCHEMA,
            "Plan",
            params,
            model="gemini/gemini-3-pro-preview",
            output_mode="strict",
        )
        assert out[_MARKER] is True
        assert out["response_format"]["type"] == "json_schema"
        assert "_mesh_hint_mode" not in out
        assert out["tools"] == _TOOLS

    def test_override_strict_falls_back_to_hint_on_gemini2x(self, monkeypatch):
        """output_mode='strict' on a model that can't server-enforce a schema
        with tools (Gemini-2.x) → safe fallback to HINT + warning, not a
        hard failure."""
        monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
        handler = GeminiHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "tools": _TOOLS,
        }
        out = handler.apply_structured_output(
            _SCHEMA,
            "Plan",
            params,
            model="gemini/gemini-2.5-flash",
            output_mode="strict",
        )
        assert out["_mesh_hint_mode"] is True
        assert _MARKER not in out

    def test_override_text_disables_schema_enforcement(self):
        """output_mode='text' → no schema enforcement (no marker, no HINT,
        no response_format)."""
        handler = GeminiHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "tools": _TOOLS,
            "response_format": {"type": "json_schema", "json_schema": {}},
        }
        out = handler.apply_structured_output(
            _SCHEMA,
            "Plan",
            params,
            model="gemini/gemini-3-pro-preview",
            output_mode="text",
        )
        assert "response_format" not in out
        assert "_mesh_hint_mode" not in out
        assert _MARKER not in out

    def test_invalid_override_ignored_falls_back_to_auto_with_warning(
        self, monkeypatch, caplog
    ):
        """Invalid override → ignored (warning) + auto. On Gemini-2.x the auto
        path is HINT."""
        monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
        handler = GeminiHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "tools": _TOOLS,
        }
        with caplog.at_level(logging.WARNING):
            out = handler.apply_structured_output(
                _SCHEMA,
                "Plan",
                params,
                model="gemini/gemini-2.5-flash",
                output_mode="bogus",
            )
        assert out["_mesh_hint_mode"] is True
        assert any("invalid output_mode" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Claude handler
# ---------------------------------------------------------------------------


_CLAUDE_CAPABLE_MODEL = "anthropic/claude-sonnet-4-6"
_CLAUDE_LEGACY_MODEL = "anthropic/claude-3-5-haiku-20241022"


@pytest.fixture
def _claude_native_on(monkeypatch):
    """Force ``ClaudeHandler.has_native()`` → True and the resolver's SDK-floor
    check → True (CI has no anthropic SDK installed). Mode SELECTION only — no
    real LLM call."""
    monkeypatch.setattr(ClaudeHandler, "has_native", lambda self: True)
    monkeypatch.setattr(caps_mod, "_sdk_at_least", lambda dist, floor: True)
    yield


@pytest.fixture
def _claude_native_off(monkeypatch):
    """Force ``ClaudeHandler.has_native()`` → False — LiteLLM path."""
    monkeypatch.setattr(ClaudeHandler, "has_native", lambda self: False)
    yield


class TestClaudeOutputModeOverride:
    def test_default_none_native_capable_uses_output_config(self, _claude_native_on):
        """No override + native + capable model → auto output_config
        (unchanged)."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, model=_CLAUDE_CAPABLE_MODEL
        )
        assert out["_mesh_output_config_mode"] is True
        assert "_mesh_hint_mode" not in out

    def test_default_none_no_native_uses_hint(self, _claude_native_off):
        """No override + no native → auto HINT (unchanged no-regression
        default)."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, model=_CLAUDE_CAPABLE_MODEL
        )
        assert out["_mesh_hint_mode"] is True
        assert "_mesh_output_config_mode" not in out

    def test_override_strict_uses_output_config_on_capable_model(
        self, _claude_native_on
    ):
        """output_mode='strict' → native server-enforced output_config when the
        model/SDK qualify (Sonnet 4.5+ / native)."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, model=_CLAUDE_CAPABLE_MODEL, output_mode="strict"
        )
        assert out["_mesh_output_config_mode"] is True
        assert out["response_format"]["type"] == "json_schema"
        assert "_mesh_hint_mode" not in out
        assert "_mesh_synthetic_format_tool" not in out

    def test_override_strict_falls_back_to_synthetic_on_legacy_model(
        self, _claude_native_on, caplog
    ):
        """output_mode='strict' on an older model that can't server-enforce a
        schema (native, but no output_config) → safe fallback to the auto
        default (synthetic-tool) + warning, not a hard failure."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        with caplog.at_level(logging.WARNING):
            out = handler.apply_structured_output(
                _SCHEMA,
                "Plan",
                params,
                model=_CLAUDE_LEGACY_MODEL,
                output_mode="strict",
            )
        assert out["_mesh_synthetic_format_tool_name"] == SYNTHETIC_FORMAT_TOOL_NAME
        assert "_mesh_output_config_mode" not in out
        assert any(
            "output_mode='strict'" in r.message for r in caplog.records
        )

    def test_override_strict_falls_back_to_hint_without_native(
        self, _claude_native_off, caplog
    ):
        """output_mode='strict' on the LiteLLM path (no native SDK) → safe
        fallback to HINT + warning."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        with caplog.at_level(logging.WARNING):
            out = handler.apply_structured_output(
                _SCHEMA,
                "Plan",
                params,
                model=_CLAUDE_CAPABLE_MODEL,
                output_mode="strict",
            )
        assert out["_mesh_hint_mode"] is True
        assert "_mesh_output_config_mode" not in out
        assert any(
            "output_mode='strict'" in r.message for r in caplog.records
        )

    def test_override_hint_forces_hint_on_capable_model(self, _claude_native_on):
        """output_mode='hint' forces prose HINT even when native + a capable
        model would auto-select output_config."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, model=_CLAUDE_CAPABLE_MODEL, output_mode="hint"
        )
        assert out["_mesh_hint_mode"] is True
        assert "_mesh_output_config_mode" not in out
        assert "response_format" not in out
        assert "OUTPUT FORMAT" in out["messages"][0]["content"]

    def test_override_text_disables_schema_enforcement(self, _claude_native_on):
        """output_mode='text' → no schema enforcement (no response_format, no
        HINT/synthetic/output_config sentinels)."""
        handler = ClaudeHandler()
        params: dict = {
            "messages": [{"role": "system", "content": "base"}],
            "response_format": {"type": "json_schema", "json_schema": {}},
        }
        out = handler.apply_structured_output(
            _SCHEMA, "Plan", params, model=_CLAUDE_CAPABLE_MODEL, output_mode="text"
        )
        assert "response_format" not in out
        assert "_mesh_hint_mode" not in out
        assert "_mesh_output_config_mode" not in out
        assert "_mesh_synthetic_format_tool" not in out

    def test_invalid_override_ignored_falls_back_to_auto_with_warning(
        self, _claude_native_on, caplog
    ):
        """Invalid override → ignored (warning) + auto. With native + a capable
        model the auto path is output_config."""
        handler = ClaudeHandler()
        params: dict = {"messages": [{"role": "system", "content": "base"}]}
        with caplog.at_level(logging.WARNING):
            out = handler.apply_structured_output(
                _SCHEMA,
                "Plan",
                params,
                model=_CLAUDE_CAPABLE_MODEL,
                output_mode="bogus",
            )
        assert out["_mesh_output_config_mode"] is True
        assert any("invalid output_mode" in r.message for r in caplog.records)
