"""Unit tests for GeminiHandler HINT-mode structured output (Phase A.6).

Background:
    Gemini 3 + ``response_format`` + tools causes non-deterministic infinite
    tool-call loops, so mesh delegation (which always involves tools) uses
    HINT mode: the schema is injected into the system prompt and validated
    by the agentic loop on every iteration. If the model emits non-JSON or
    schema-non-conforming JSON, the loop falls back to a bounded-timeout
    ``response_format`` retry with tools stripped (the constraint doesn't
    apply tools-absent).

    Prior to Phase A.6, ``GeminiHandler.apply_structured_output`` injected
    the schema text into the system message but did NOT stamp the
    ``_mesh_hint_*`` sentinels — so ``_maybe_run_hint_fallback`` would
    short-circuit and raw prose would leak to the consumer. This suite
    locks in the sentinel-stamping fix and the no-system-message synthesis
    path.
"""

from __future__ import annotations

import os

import pytest

from _mcp_mesh.engine.provider_handlers import base_provider_handler
from _mcp_mesh.engine.provider_handlers.gemini_handler import GeminiHandler


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The answer text"},
            "confidence": {"type": "number"},
        },
        "required": ["answer", "confidence"],
    }


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip both env-var forms between tests to avoid cross-test leakage."""
    monkeypatch.delenv("MCP_MESH_HINT_FALLBACK_TIMEOUT", raising=False)
    monkeypatch.delenv("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT", raising=False)
    base_provider_handler._reset_legacy_hint_timeout_dedupe()
    yield
    base_provider_handler._reset_legacy_hint_timeout_dedupe()


class TestGeminiApplyStructuredOutputHintMode:
    """Verify HINT sentinel stamping on GeminiHandler."""

    def test_stamps_mesh_hint_sentinels(self):
        handler = GeminiHandler()
        model_params = {
            "messages": [{"role": "system", "content": "You are helpful."}],
        }
        result = handler.apply_structured_output(_schema(), "MyType", model_params)

        assert result.get("_mesh_hint_mode") is True
        assert isinstance(result.get("_mesh_hint_schema"), dict)
        assert "answer" in result["_mesh_hint_schema"].get("properties", {})
        assert result.get("_mesh_hint_fallback_timeout") == 90
        assert result.get("_mesh_hint_output_type_name") == "MyType"

    def test_appends_hint_to_existing_system_message(self):
        handler = GeminiHandler()
        model_params = {
            "messages": [
                {"role": "system", "content": "You are X."},
                {"role": "user", "content": "Hi."},
            ],
        }
        handler.apply_structured_output(_schema(), "MyType", model_params)
        sys_content = model_params["messages"][0]["content"]
        assert sys_content.startswith("You are X.")
        assert "OUTPUT FORMAT:" in sys_content
        assert "answer" in sys_content
        # Non-system messages untouched.
        assert model_params["messages"][1]["content"] == "Hi."

    def test_synthesizes_system_message_when_missing(self):
        """If no system message exists, one is synthesized at index 0
        containing the HINT block. Without this the model would never see
        the schema and the fallback timeout would fire on every request."""
        handler = GeminiHandler()
        model_params = {
            "messages": [{"role": "user", "content": "Hi."}],
        }
        handler.apply_structured_output(_schema(), "MyType", model_params)
        assert model_params["messages"][0]["role"] == "system"
        assert "OUTPUT FORMAT:" in model_params["messages"][0]["content"]
        # Original user message preserved at index 1.
        assert model_params["messages"][1] == {"role": "user", "content": "Hi."}

    def test_synthesizes_system_message_when_messages_empty(self):
        handler = GeminiHandler()
        model_params = {"messages": []}
        handler.apply_structured_output(_schema(), "MyType", model_params)
        assert len(model_params["messages"]) == 1
        assert model_params["messages"][0]["role"] == "system"
        assert "OUTPUT FORMAT:" in model_params["messages"][0]["content"]

    def test_pops_response_format_defense_in_depth(self):
        """If the caller passes ``response_format`` it MUST be popped — the
        HINT path is the workaround for the Gemini 3 infinite-tool-loop
        bug that fires when response_format + tools are combined."""
        handler = GeminiHandler()
        model_params = {
            "messages": [{"role": "system", "content": "X"}],
            "response_format": {"type": "json_schema"},
        }
        result = handler.apply_structured_output(_schema(), "MyType", model_params)
        assert "response_format" not in result

    def test_env_timeout_override_parses(self, monkeypatch):
        monkeypatch.setenv("MCP_MESH_HINT_FALLBACK_TIMEOUT", "120")
        handler = GeminiHandler()
        model_params = {"messages": [{"role": "system", "content": "X"}]}
        result = handler.apply_structured_output(_schema(), "MyType", model_params)
        assert result["_mesh_hint_fallback_timeout"] == 120

    def test_env_timeout_malformed_uses_default(self, monkeypatch, caplog):
        monkeypatch.setenv("MCP_MESH_HINT_FALLBACK_TIMEOUT", "not-an-int")
        handler = GeminiHandler()
        model_params = {"messages": [{"role": "system", "content": "X"}]}
        with caplog.at_level(
            "WARNING", logger=base_provider_handler.logger.name
        ):
            result = handler.apply_structured_output(
                _schema(), "MyType", model_params
            )
        assert result["_mesh_hint_fallback_timeout"] == 90
        assert any(
            "not an integer" in r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
        )

    def test_env_timeout_zero_or_negative_uses_default(self, monkeypatch):
        monkeypatch.setenv("MCP_MESH_HINT_FALLBACK_TIMEOUT", "0")
        handler = GeminiHandler()
        model_params = {"messages": [{"role": "system", "content": "X"}]}
        result = handler.apply_structured_output(_schema(), "MyType", model_params)
        assert result["_mesh_hint_fallback_timeout"] == 90

    def test_no_handler_instance_state_pollution(self):
        """Singleton handler must not retain per-request schema state."""
        handler = GeminiHandler()
        model_params = {"messages": [{"role": "system", "content": "X"}]}
        handler.apply_structured_output(_schema(), "MyType", model_params)
        assert not hasattr(handler, "_pending_output_schema")
        assert not hasattr(handler, "_pending_output_type_name")


class TestHintFallbackTimeoutEnvBackCompat:
    """Lock in the env-var rename + back-compat alias semantics.

    ``MCP_MESH_HINT_FALLBACK_TIMEOUT`` is the canonical vendor-agnostic
    knob. ``MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT`` is preserved as a
    back-compat alias with a one-time deprecation warning. Canonical wins
    on collision.
    """

    def test_legacy_env_var_still_honored_with_deprecation_warning(
        self, monkeypatch, caplog
    ):
        monkeypatch.setenv("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT", "120")
        base_provider_handler._reset_legacy_hint_timeout_dedupe()
        with caplog.at_level(
            "WARNING", logger=base_provider_handler.logger.name
        ):
            timeout = base_provider_handler.resolve_hint_fallback_timeout()
        assert timeout == 120
        deprecation_warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT" in r.getMessage()
            and "deprecated" in r.getMessage()
        ]
        assert len(deprecation_warns) == 1, (
            f"Expected exactly one deprecation warning; got: {deprecation_warns}"
        )

    def test_canonical_env_var_wins_when_both_set(self, monkeypatch, caplog):
        monkeypatch.setenv("MCP_MESH_HINT_FALLBACK_TIMEOUT", "45")
        monkeypatch.setenv("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT", "120")
        base_provider_handler._reset_legacy_hint_timeout_dedupe()
        with caplog.at_level(
            "WARNING", logger=base_provider_handler.logger.name
        ):
            timeout = base_provider_handler.resolve_hint_fallback_timeout()
        assert timeout == 45
        # Deprecation warning still fires because the legacy var was set
        # — operator gets told it's now ignored on this host.
        deprecation_warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT" in r.getMessage()
            and "deprecated" in r.getMessage()
        ]
        assert len(deprecation_warns) == 1

    def test_deprecation_warning_fires_only_once_per_process(
        self, monkeypatch, caplog
    ):
        monkeypatch.setenv("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT", "120")
        base_provider_handler._reset_legacy_hint_timeout_dedupe()
        with caplog.at_level(
            "WARNING", logger=base_provider_handler.logger.name
        ):
            base_provider_handler.resolve_hint_fallback_timeout()
            base_provider_handler.resolve_hint_fallback_timeout()
            base_provider_handler.resolve_hint_fallback_timeout()
        deprecation_warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT" in r.getMessage()
            and "deprecated" in r.getMessage()
        ]
        assert len(deprecation_warns) == 1

    def test_no_env_vars_returns_default(self):
        # Both env vars cleared by autouse fixture.
        timeout = base_provider_handler.resolve_hint_fallback_timeout()
        assert timeout == 90

    def test_canonical_only_no_deprecation_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("MCP_MESH_HINT_FALLBACK_TIMEOUT", "60")
        base_provider_handler._reset_legacy_hint_timeout_dedupe()
        with caplog.at_level(
            "WARNING", logger=base_provider_handler.logger.name
        ):
            timeout = base_provider_handler.resolve_hint_fallback_timeout()
        assert timeout == 60
        deprecation_warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "deprecated" in r.getMessage()
        ]
        assert deprecation_warns == []
